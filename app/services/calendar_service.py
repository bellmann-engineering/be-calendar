"""
Anbindung an die Google Calendar API.

Was macht diese Datei?
    * ``list_calendars()``   – alle Kalender, die das verbundene Google-Konto sieht
                               (für die Zuordnung zu Mitarbeitern).
    * ``check_calendar()``   – "Verbindung prüfen": Kommt die App an diesen Kalender heran,
                               und mit welchen Rechten?
    * ``get_busy_times()`` / ``get_busy_map()``
                             – Frei/Belegt-Zeiten eines oder vieler Kalender (Kollisions-
                               prüfung und graue "Belegt"-Blöcke in der Oberfläche).
    * ``insert_event()`` / ``update_event()`` / ``delete_event()``
                             – Termine in den Google-Kalender eines Mitarbeiters spiegeln
                               (genutzt von app/services/google_sync_service.py).

Woher kommen die Zugangsdaten?
    Ausschließlich aus der OAuth-Verbindung (Tabelle ``google_connections``): Ein CEO/ADMIN
    hat sein Google-Konto einmalig verbunden (app/services/google_oauth_service.py). Die
    App handelt dann mit SEINEN Rechten – sie sieht genau die Kalender, die er sieht.
    Ohne Verbindung sind alle Methoden No-Ops – die App läuft einfach ohne Google.
    (Bewusst KEIN versteckter Service-Account als Rückfallebene: Was die App mit Google
    macht, soll immer an der sichtbaren Verbindung auf der Mitarbeiter-Seite hängen.)

Thread-Sicherheit (wichtig für Gunicorn mit gthread-Workern!):
    ``googleapiclient`` nutzt ``httplib2``, und ``httplib2.Http`` ist NICHT threadsicher.
    Deshalb bekommt jeder Thread über ``threading.local`` sein eigenes Service-Objekt.
    Die Credentials werden pro Prozess zwischengespeichert – so wird das Access-Token
    wiederverwendet, statt es bei jeder Anfrage neu bei Google abzuholen.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta

from flask import current_app

from app.utils.time import isoformat_utc, utc_now

logger = logging.getLogger(__name__)

# Berechtigungen, die beim Verbinden angefragt werden (siehe google_oauth_service.py):
#   calendar.readonly -> Kalenderliste + Frei/Belegt lesen
#   calendar.events   -> Termine in Kalender schreiben, auf die das Konto Schreibrechte hat
OAUTH_SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar.events",
]
TOKEN_URI = "https://oauth2.googleapis.com/token"  # noqa: S105 - öffentliche URL, kein Geheimnis
# Timeout für HTTP-Aufrufe an Google. Ohne Timeout könnte ein hängender Aufruf einen
# Gunicorn-Thread blockieren, bis Gunicorn den ganzen Worker abschießt.
_HTTP_TIMEOUT_SECONDS = 10
# Die Free/Busy-API akzeptiert höchstens 50 Kalender pro Anfrage.
_FREEBUSY_MAX = 50

_thread_local = threading.local()
_credentials_cache: dict[str, object] = {}
_credentials_lock = threading.Lock()
_busy_cache: dict[tuple, tuple[float, dict]] = {}
_busy_lock = threading.Lock()

# Übersetzung der Google-Rechte für Meldungen an den Benutzer.
ROLLEN_DE = {
    "owner": "Besitzer",
    "writer": "Bearbeiten",
    "reader": "Nur lesen",
    "freeBusyReader": "Nur Frei/Belegt",
}


class GoogleApiFehler(Exception):
    """Google war nicht erreichbar oder hat die Anfrage abgelehnt (Details im Log)."""


def _oauth_credentials() -> tuple[str, object] | None:
    """Credentials aus der gespeicherten OAuth-Verbindung (oder None)."""
    from app.models import GoogleConnection
    from app.utils.crypto import decrypt_text

    verbindung = GoogleConnection.query.order_by(GoogleConnection.id.desc()).first()
    if verbindung is None:
        return None
    # Der Schlüssel ändert sich bei jeder neuen Verbindung -> alter Cache wird ignoriert.
    schluessel = f"oauth:{verbindung.id}:{verbindung.updated_at.timestamp()}"
    with _credentials_lock:
        if schluessel in _credentials_cache:
            return schluessel, _credentials_cache[schluessel]
    refresh_token = decrypt_text(verbindung.refresh_token_enc)
    if not refresh_token:
        logger.error(
            "Google-Refresh-Token nicht entschlüsselbar (SECRET_KEY geändert?) – "
            "bitte Google-Konto neu verbinden."
        )
        return None
    from google.oauth2.credentials import Credentials

    cfg = current_app.config
    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        client_id=cfg["GOOGLE_OAUTH_CLIENT_ID"],
        client_secret=cfg["GOOGLE_OAUTH_CLIENT_SECRET"],
        token_uri=TOKEN_URI,
        scopes=verbindung.scopes.split() or OAUTH_SCOPES,
    )
    with _credentials_lock:
        _credentials_cache.clear()  # nur die aktuelle Verbindung behalten
        _credentials_cache[schluessel] = creds
    return schluessel, creds


class GoogleCalendarService:
    """Dünne Hülle um die Google Calendar API."""

    def __init__(self) -> None:
        self.quelle: str | None = None  # "oauth" oder None
        self.service = self._get_thread_service()

    # ------------------------------------------------------------------ Verbindung
    def _get_thread_service(self) -> object | None:
        """Service-Objekt des aktuellen Threads – neu gebaut, wenn sich der Zugang ändert."""
        gefunden = _oauth_credentials()
        if gefunden is None:
            return None
        schluessel, credentials = gefunden
        self.quelle = schluessel.split(":", 1)[0]
        zwischen = getattr(_thread_local, "eintrag", None)
        if zwischen and zwischen[0] == schluessel:
            return zwischen[1]

        import google_auth_httplib2
        import httplib2
        from googleapiclient.discovery import build

        # Eigenes Http-Objekt MIT Timeout, durch AuthorizedHttp um OAuth ergänzt.
        # AuthorizedHttp erneuert abgelaufene Access-Tokens automatisch.
        authed_http = google_auth_httplib2.AuthorizedHttp(
            credentials, http=httplib2.Http(timeout=_HTTP_TIMEOUT_SECONDS)
        )
        # cache_discovery=False: nutzt die mitgelieferte API-Beschreibung statt sie bei
        # jedem Start aus dem Internet zu laden.
        service = build("calendar", "v3", http=authed_http, cache_discovery=False)
        _thread_local.eintrag = (schluessel, service)
        return service

    @property
    def verfuegbar(self) -> bool:
        return self.service is not None

    # ------------------------------------------------------------------ Kalender
    def list_calendars(self) -> list[dict]:
        """Alle Kalender der Kalenderliste des verbundenen Kontos.

        Raises:
            GoogleApiFehler: Wenn Google nicht antwortet oder den Zugriff verweigert.
        """
        if not self.service:
            return []
        kalender: list[dict] = []
        seite = None
        try:
            while True:
                antwort = (
                    self.service.calendarList()
                    .list(pageToken=seite, minAccessRole="freeBusyReader", showHidden=False)
                    .execute()
                )
                for eintrag in antwort.get("items", []):
                    kalender.append(
                        {
                            "id": eintrag["id"],
                            "summary": eintrag.get("summaryOverride")
                            or eintrag.get("summary")
                            or eintrag["id"],
                            "access_role": eintrag.get("accessRole", "reader"),
                            "primary": bool(eintrag.get("primary", False)),
                            "color": eintrag.get("backgroundColor"),
                        }
                    )
                seite = antwort.get("nextPageToken")
                if not seite:
                    break
        except Exception as exc:  # noqa: BLE001 - jede Google-Störung gleich behandeln
            logger.exception("Kalenderliste von Google konnte nicht geladen werden")
            raise GoogleApiFehler("Google-Kalenderliste nicht abrufbar.") from exc
        # Hauptkalender zuerst, dann alphabetisch.
        return sorted(kalender, key=lambda k: (not k["primary"], k["summary"].lower()))

    def check_calendar(self, calendar_id: str) -> tuple[bool, str | None, str]:
        """Prüft den Zugriff auf einen Kalender. Rückgabe: (ok, rechte, deutsche Meldung)."""
        if not self.service:
            return False, None, "Keine Google-Verbindung eingerichtet."
        rolle = None
        try:
            eintrag = self.service.calendarList().get(calendarId=calendar_id).execute()
            rolle = eintrag.get("accessRole")
        except Exception:  # noqa: BLE001 - nicht in der Liste -> unten per Free/Busy testen
            logger.info("Kalender %s nicht in der Kalenderliste – prüfe Frei/Belegt", calendar_id)
        try:
            # Minimaler Zeitraum (1 Minute) – es geht nur darum, ob Google Zugriff gewährt.
            jetzt = utc_now()
            body = {
                "timeMin": isoformat_utc(jetzt),
                "timeMax": isoformat_utc(jetzt + timedelta(minutes=1)),
                "items": [{"id": calendar_id}],
            }
            antwort = self.service.freebusy().query(body=body).execute()
            fehler = antwort.get("calendars", {}).get(calendar_id, {}).get("errors")
        except Exception:  # noqa: BLE001
            logger.warning("Frei/Belegt-Prüfung für %s fehlgeschlagen", calendar_id, exc_info=True)
            return (
                False,
                rolle,
                "Google ist gerade nicht erreichbar. Bitte später erneut versuchen.",
            )
        if fehler:
            return (
                False,
                rolle,
                "Kein Zugriff auf diesen Kalender. Er muss mit dem verbundenen Google-Konto "
                "geteilt sein.",
            )
        rolle = rolle or "freeBusyReader"
        text = f"Verbindung in Ordnung – Rechte: {ROLLEN_DE.get(rolle, rolle)}."
        if rolle not in {"owner", "writer"}:
            text += " Termine können angezeigt, aber nicht in diesen Kalender übertragen werden."
        return True, rolle, text

    # ------------------------------------------------------------------ Frei/Belegt
    def get_busy_times(
        self, calendar_id: str, time_min: datetime, time_max: datetime
    ) -> list[dict[str, str]]:
        """Belegte Zeitblöcke eines Kalenders – leer bei Fehler/ohne Google."""
        return self.get_busy_map([calendar_id], time_min, time_max).get(calendar_id, [])

    def get_busy_map(
        self, calendar_ids: list[str], time_min: datetime, time_max: datetime
    ) -> dict[str, list[dict[str, str]]]:
        """Belegte Zeitblöcke vieler Kalender in möglichst wenigen Anfragen (je 50).

        Ergebnis wird kurz zwischengespeichert (GOOGLE_BUSY_CACHE_SECONDS), damit mehrere
        gleichzeitige Kalenderansichten Google nicht mehrfach fragen.
        """
        ids = sorted({c for c in calendar_ids if c})
        if not self.service or not ids:
            return {}
        ttl = current_app.config.get("GOOGLE_BUSY_CACHE_SECONDS", 60)
        cache_key = (self.quelle, tuple(ids), isoformat_utc(time_min), isoformat_utc(time_max))
        if ttl:
            with _busy_lock:
                treffer = _busy_cache.get(cache_key)
                if treffer and treffer[0] > time.monotonic():
                    return treffer[1]
        ergebnis: dict[str, list[dict[str, str]]] = {}
        for i in range(0, len(ids), _FREEBUSY_MAX):
            teil = ids[i : i + _FREEBUSY_MAX]
            try:
                body = {
                    "timeMin": isoformat_utc(time_min),
                    "timeMax": isoformat_utc(time_max),
                    "items": [{"id": c} for c in teil],
                }
                antwort = self.service.freebusy().query(body=body).execute()
            except Exception:  # noqa: BLE001 - Google darf die Terminplanung nie blockieren
                logger.exception("Frei/Belegt-Abfrage bei Google fehlgeschlagen")
                continue
            for cal_id, daten in antwort.get("calendars", {}).items():
                if daten.get("errors"):
                    logger.info("Kein Frei/Belegt-Zugriff auf %s: %s", cal_id, daten["errors"])
                    continue
                ergebnis[cal_id] = daten.get("busy", [])
        if ttl:
            with _busy_lock:
                if len(_busy_cache) > 500:  # Speicher begrenzen
                    _busy_cache.clear()
                _busy_cache[cache_key] = (time.monotonic() + ttl, ergebnis)
        return ergebnis

    # ------------------------------------------------------------------ Termine spiegeln
    @staticmethod
    def _event_body(
        title: str, start_time: datetime, end_time: datetime, description: str | None
    ) -> dict:
        return {
            "summary": title,
            "description": description or "Automatisch erstellt via Bellmann Eng.",
            "start": {"dateTime": isoformat_utc(start_time), "timeZone": "UTC"},
            "end": {"dateTime": isoformat_utc(end_time), "timeZone": "UTC"},
        }

    def insert_event(
        self,
        calendar_id: str,
        title: str,
        start_time: datetime,
        end_time: datetime,
        description: str | None = "",
    ) -> str | None:
        """Legt einen Termin an. Gibt die Google-Event-ID zurück oder None."""
        if not self.service:
            return None
        try:
            event = (
                self.service.events()
                .insert(
                    calendarId=calendar_id,
                    body=self._event_body(title, start_time, end_time, description),
                )
                .execute()
            )
            logger.info("Termin in Google-Kalender %s angelegt.", calendar_id)
            return event.get("id")
        except Exception:  # noqa: BLE001
            logger.warning(
                "Schreiben in Google-Kalender %s fehlgeschlagen (Schreibrechte?)",
                calendar_id,
                exc_info=True,
            )
            return None

    def update_event(
        self,
        calendar_id: str,
        event_id: str,
        title: str,
        start_time: datetime,
        end_time: datetime,
        description: str | None = "",
    ) -> bool:
        """Ändert einen gespiegelten Termin (PATCH = nur die angegebenen Felder)."""
        if not self.service or not event_id:
            return False
        try:
            self.service.events().patch(
                calendarId=calendar_id,
                eventId=event_id,
                body=self._event_body(title, start_time, end_time, description),
            ).execute()
            return True
        except Exception:  # noqa: BLE001
            logger.warning("Google-Termin %s konnte nicht geändert werden", event_id, exc_info=True)
            return False

    def delete_event(self, calendar_id: str, event_id: str | None) -> bool:
        """Löscht einen gespiegelten Termin. Fehler werden geloggt, nicht geworfen."""
        if not self.service or not event_id:
            return False
        try:
            self.service.events().delete(calendarId=calendar_id, eventId=event_id).execute()
            logger.info("Google-Termin %s in %s gelöscht.", event_id, calendar_id)
            return True
        except Exception:  # noqa: BLE001
            logger.warning("Google-Termin %s konnte nicht gelöscht werden", event_id, exc_info=True)
            return False


def cache_leeren() -> None:
    """Vergisst gespeicherte Zugangsdaten und Frei/Belegt-Antworten (nach Verbinden/Trennen)."""
    with _credentials_lock:
        _credentials_cache.clear()
    with _busy_lock:
        _busy_cache.clear()
    if hasattr(_thread_local, "eintrag"):
        del _thread_local.eintrag
