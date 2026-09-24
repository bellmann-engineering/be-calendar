"""
Anbindung an die Google Calendar API (optional).

Was macht diese Datei?
    * ``get_busy_times()`` – fragt über die Free/Busy-API ab, wann ein Mitarbeiter in
                             seinem privaten Google-Kalender belegt ist
                             (genutzt von EventService.check_conflict()).
    * ``insert_event()``   – spiegelt einen neu angelegten Termin in den Google-Kalender.
    * ``delete_event()``   – entfernt den gespiegelten Termin wieder (beim Soft-Delete).

Womit spricht sie?
    Mit https://www.googleapis.com/calendar/v3 über einen Service-Account.
    Zugangsdaten: JSON-Datei unter ``GOOGLE_CREDENTIALS_FILE`` (Standard:
    ``./secrets/google_credentials.json``; in Docker read-only nach /run/secrets
    eingehängt). Die Datei muss für den Container-Benutzer (UID 10001) lesbar sein.
    Der jeweilige Mitarbeiter muss seinen Kalender für die Service-Account-Adresse
    freigeben (siehe scripts/test_google_api.py).

Fehlt die Datei, sind alle Methoden No-Ops – die App läuft dann einfach ohne Google.

Thread-Sicherheit (wichtig für Gunicorn mit gthread-Workern!):
    ``googleapiclient`` nutzt ``httplib2``, und ``httplib2.Http`` ist NICHT threadsicher.
    Deshalb bekommt jeder Thread über ``threading.local`` sein eigenes Service-Objekt.
    Die (unveränderlichen) Credentials werden dagegen einmal pro Prozess geladen.
"""

import logging
import os
import threading
from datetime import datetime

from flask import current_app

from app.utils.time import isoformat_utc

logger = logging.getLogger(__name__)

_SCOPES = ["https://www.googleapis.com/auth/calendar"]
# Timeout für HTTP-Aufrufe an Google. Ohne Timeout könnte ein hängender Aufruf einen
# Gunicorn-Thread blockieren, bis Gunicorn den ganzen Worker abschießt.
_HTTP_TIMEOUT_SECONDS = 10

_thread_local = threading.local()
_credentials_cache: dict[str, object] = {}
_credentials_lock = threading.Lock()


def _load_credentials(path: str) -> object | None:
    """Lädt die Service-Account-Credentials einmal pro Prozess (thread-sicher gecacht)."""
    with _credentials_lock:
        if path in _credentials_cache:
            return _credentials_cache[path]
        if not os.path.exists(path):
            logger.warning(
                "Google-Credentials nicht gefunden (%s) – Google-Kalender deaktiviert.", path
            )
            _credentials_cache[path] = None
            return None
        # Import erst hier: Die Google-Bibliotheken sind groß und werden ohne
        # Credentials-Datei gar nicht gebraucht.
        from google.oauth2 import service_account

        creds = service_account.Credentials.from_service_account_file(path, scopes=_SCOPES)
        _credentials_cache[path] = creds
        return creds


class GoogleCalendarService:
    """Dünne Hülle um die Google Calendar API (Free/Busy, Termine anlegen/löschen)."""

    def __init__(self) -> None:
        self.credentials_path: str = current_app.config["GOOGLE_CREDENTIALS_FILE"]
        self.service = self._get_thread_service()

    def _get_thread_service(self) -> object | None:
        """Liefert das Google-API-Service-Objekt des aktuellen Threads (oder None)."""
        cached = getattr(_thread_local, "service", None)
        if cached is not None:
            return cached

        credentials = _load_credentials(self.credentials_path)
        if credentials is None:
            return None

        import google_auth_httplib2
        import httplib2
        from googleapiclient.discovery import build

        # Eigenes Http-Objekt MIT Timeout, durch AuthorizedHttp um OAuth ergänzt.
        authed_http = google_auth_httplib2.AuthorizedHttp(
            credentials, http=httplib2.Http(timeout=_HTTP_TIMEOUT_SECONDS)
        )
        # cache_discovery=False: nutzt die in der Bibliothek mitgelieferte API-Beschreibung
        # statt sie bei jedem Start aus dem Internet zu laden.
        service = build("calendar", "v3", http=authed_http, cache_discovery=False)
        _thread_local.service = service
        return service

    def get_busy_times(
        self, calendar_id: str, time_min: datetime, time_max: datetime
    ) -> list[dict[str, str]]:
        """Belegte Zeitblöcke im Zeitraum [time_min, time_max) – leer bei Fehler/ohne Google.

        Returns:
            Liste wie ``[{"start": "2026-09-25T08:00:00Z", "end": "..."}]``.
        """
        if not self.service:
            return []
        try:
            body = {
                # isoformat_utc liefert bereits "+00:00" – früher wurde fälschlich ein
                # zusätzliches "Z" an naive Zeiten angehängt.
                "timeMin": isoformat_utc(time_min),
                "timeMax": isoformat_utc(time_max),
                "items": [{"id": calendar_id}],
            }
            result = self.service.freebusy().query(body=body).execute()
            return result["calendars"][calendar_id]["busy"]
        except Exception:  # noqa: BLE001 - Google darf die Terminplanung nie blockieren
            logger.exception("Free/Busy-Abfrage für %s fehlgeschlagen", calendar_id)
            return []

    def insert_event(
        self,
        calendar_id: str,
        title: str,
        start_time: datetime,
        end_time: datetime,
        description: str | None = "",
    ) -> str | None:
        """Legt einen Termin im Google-Kalender an. Gibt die Google-Event-ID zurück oder None."""
        if not self.service:
            return None
        try:
            event_body = {
                "summary": title,
                "description": description or "Automatisch erstellt via Bellmann Dashboard",
                "start": {"dateTime": isoformat_utc(start_time), "timeZone": "UTC"},
                "end": {"dateTime": isoformat_utc(end_time), "timeZone": "UTC"},
            }
            event = self.service.events().insert(calendarId=calendar_id, body=event_body).execute()
            logger.info("Termin in Google-Kalender %s erstellt.", calendar_id)
            return event.get("id")
        except Exception:  # noqa: BLE001
            logger.exception("Schreiben in Google-Kalender %s fehlgeschlagen", calendar_id)
            return None

    def delete_event(self, calendar_id: str, event_id: str | None) -> None:
        """Löscht einen gespiegelten Termin. Fehler werden geloggt, nicht geworfen."""
        if not self.service or not event_id:
            return
        try:
            self.service.events().delete(calendarId=calendar_id, eventId=event_id).execute()
            logger.info("Google-Termin %s in %s gelöscht.", event_id, calendar_id)
        except Exception:  # noqa: BLE001
            logger.warning("Google-Termin %s konnte nicht gelöscht werden", event_id, exc_info=True)
