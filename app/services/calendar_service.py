"""
Anbindung an die Google Calendar API.

Was macht diese Datei?
    * ``list_calendars()``   – alle Kalender, die das verbundene Google-Konto sieht
                               (für die Zuordnung zu Mitarbeitern).
    * ``check_calendar()``   – "Verbindung prüfen": Kommt die App an diesen Kalender heran,
                               und mit welchen Rechten?
    * ``list_events()``      – Termine eines oder vieler Kalender (mit Titel) zur Anzeige
                               im Kalender der App (GET /api/v1/google/events).
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

import html
import logging
import re
import threading
import time
from datetime import datetime

from flask import current_app

from app.utils.time import isoformat_utc

logger = logging.getLogger(__name__)

# Berechtigungen, die beim Verbinden angefragt werden (siehe google_oauth_service.py):
#   calendar.readonly -> Kalenderliste + Termine lesen
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
# Höchstens 4 Seiten à 250 Termine pro Kalender und Abruf (Schutz vor Endlosschleifen).
_MAX_EVENT_PAGES = 4
# Markierung für Termine, die die App selbst in Google anlegt (siehe _event_body): Beim
# Lesen werden sie ausgelassen, sonst stünden sie doppelt im Kalender.
APP_MARKER_KEY = "bellmann_app"

_thread_local = threading.local()
_credentials_cache: dict[str, object] = {}
_credentials_lock = threading.Lock()
_events_cache: dict[tuple, tuple[float, tuple]] = {}
_events_lock = threading.Lock()

# Übersetzung der Google-Rechte für Meldungen an den Benutzer.
ROLLEN_DE = {
    "owner": "Besitzer",
    "writer": "Bearbeiten",
    "reader": "Nur lesen",
    "freeBusyReader": "Nur Frei/Belegt (reicht nicht zum Anzeigen)",
}


class GoogleApiFehler(Exception):
    """Google war nicht erreichbar oder hat die Anfrage abgelehnt (Details im Log)."""


# Beschreibung aus Google (oft HTML) -> reiner Text. Links bleiben als URL erhalten,
# damit das Frontend sie als sichere <a>-Elemente darstellen kann (nie als HTML!).
_HTML_LINK = re.compile(r"""<a\b[^>]*?href\s*=\s*["']([^"']+)["'][^>]*>(.*?)</a\s*>""", re.I | re.S)
_HTML_BREAK = re.compile(r"<\s*(?:br|/?p|/?div|/?ul|/?ol|/li|/h[1-6]|/tr)\b[^>]*>", re.I)
_HTML_LI = re.compile(r"<\s*li\b[^>]*>", re.I)
_HTML_TAG = re.compile(r"<[^>]+>")
_MAX_DESCRIPTION = 5000
_MAX_ATTENDEES = 50


def _link_als_text(treffer: re.Match) -> str:
    ziel = html.unescape(treffer.group(1)).strip()
    text = html.unescape(_HTML_TAG.sub("", treffer.group(2))).strip()
    return ziel if not text or text == ziel else f"{text} ({ziel})"


def beschreibung_als_text(roh: str | None) -> str | None:
    """Google-Beschreibung (HTML oder Text) -> lesbarer Text mit Zeilenumbrüchen."""
    if not roh:
        return None
    text = _HTML_LINK.sub(_link_als_text, roh)
    text = _HTML_BREAK.sub("\n", text)
    text = _HTML_LI.sub("• ", text)
    text = html.unescape(_HTML_TAG.sub("", text)).replace("\xa0", " ")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text[:_MAX_DESCRIPTION] or None


# Teams/Zoom/Meet-Links, die nur in der Beschreibung stehen (z. B. aus Outlook-Einladungen).
_MEETING_IN_TEXT = re.compile(
    r"https://(?:teams\.microsoft\.com/l/meetup-join/|teams\.live\.com/meet/"
    r"|[\w.-]*zoom\.us/j/|meet\.google\.com/)[^\s<>\"')\]]+",
    re.I,
)


def _meeting_link(eintrag: dict, beschreibung: str | None = None) -> str | None:
    """Videokonferenz-Link: Google Meet / Konferenzdaten, sonst aus Ort oder Beschreibung."""
    if eintrag.get("hangoutLink"):
        return eintrag["hangoutLink"]
    for punkt in (eintrag.get("conferenceData") or {}).get("entryPoints") or []:
        if punkt.get("entryPointType") == "video" and punkt.get("uri"):
            return punkt["uri"]
    for text in (eintrag.get("location"), beschreibung):
        treffer = _MEETING_IN_TEXT.search(text or "")
        if treffer:
            return treffer.group(0)
    return None


def _teilnehmer(eintrag: dict) -> list[dict]:
    """Teilnehmer ohne Räume/Ressourcen, höchstens 50."""
    liste = []
    for person in eintrag.get("attendees") or []:
        if person.get("resource"):
            continue
        liste.append(
            {
                "name": person.get("displayName") or person.get("email") or "Unbekannt",
                "email": person.get("email"),
                # accepted | declined | tentative | needsAction
                "status": person.get("responseStatus") or "needsAction",
                "organizer": bool(person.get("organizer")),
            }
        )
        if len(liste) >= _MAX_ATTENDEES:
            break
    return liste


def _termin_aus_google(eintrag: dict) -> dict | None:
    """Google-Termin -> schlanke Darstellung für das Frontend (oder None = auslassen).

    Ganztägig: Google liefert ``date`` (Ende exklusiv, wie FullCalendar), sonst
    ``dateTime`` mit Zeitzone.
    """
    if eintrag.get("status") == "cancelled":
        return None
    privat = (eintrag.get("extendedProperties") or {}).get("private") or {}
    if privat.get(APP_MARKER_KEY):
        return None  # von der App selbst übertragen
    beginn, ende = eintrag.get("start") or {}, eintrag.get("end") or {}
    ganztaegig = "date" in beginn
    start = beginn.get("date") if ganztaegig else beginn.get("dateTime")
    stop = ende.get("date") if ganztaegig else ende.get("dateTime")
    if not start or not stop:
        return None
    beschreibung = beschreibung_als_text(eintrag.get("description"))
    return {
        "id": eintrag.get("id"),
        "title": eintrag.get("summary") or "(Ohne Titel)",
        "start": start,
        "end": stop,
        "all_day": ganztaegig,
        "location": eintrag.get("location") or None,
        "html_link": eintrag.get("htmlLink") or None,
        # Details für das Termin-Fenster (Links und Zusatzinfos stehen oft hier).
        "description": beschreibung,
        "meeting_url": _meeting_link(eintrag, beschreibung),
        "attendees": _teilnehmer(eintrag),
        "organizer": (
            (eintrag.get("organizer") or {}).get("displayName")
            or (eintrag.get("organizer") or {}).get("email")
        ),
        # Serientermine: gemeinsame ID -> eine Meldung pro neuer Serie (Glocke).
        "series_id": eintrag.get("recurringEventId"),
    }


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
                    # "reader": Nur Kalender, deren Termine die App auch anzeigen kann.
                    .list(pageToken=seite, minAccessRole="reader", showHidden=False).execute()
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
        except Exception:  # noqa: BLE001 - nicht in der Liste -> unten direkt testen
            logger.info("Kalender %s nicht in der Kalenderliste – prüfe Lesezugriff", calendar_id)
        try:
            # Ein einziger Termin reicht: Es geht nur darum, ob Google Lesezugriff gewährt.
            self.service.events().list(calendarId=calendar_id, maxResults=1).execute()
        except Exception as exc:  # noqa: BLE001
            status = getattr(getattr(exc, "resp", None), "status", None)
            if status in (403, 404):
                return (
                    False,
                    rolle,
                    "Kein Lesezugriff auf diesen Kalender. Er muss mit dem verbundenen "
                    "Google-Konto geteilt sein – mindestens mit „Alle Termindetails sehen“.",
                )
            logger.warning("Zugriffsprüfung für %s fehlgeschlagen", calendar_id, exc_info=True)
            return (
                False,
                rolle,
                "Google ist gerade nicht erreichbar. Bitte später erneut versuchen.",
            )
        rolle = rolle or "reader"
        text = f"Verbindung in Ordnung – Rechte: {ROLLEN_DE.get(rolle, rolle)}."
        if rolle not in {"owner", "writer"}:
            text += (
                " Termine werden angezeigt, aber App-Termine nicht in diesen Kalender übertragen."
            )
        return True, rolle, text

    # ------------------------------------------------------------------ Termine lesen
    def list_events(
        self, calendar_ids: list[str], time_min: datetime, time_max: datetime
    ) -> tuple[dict[str, list[dict]], dict[str, str]]:
        """Termine mehrerer Kalender im Zeitraum – zur Anzeige im Kalender der App.

        Alle Einträge kommen mit: ganztägige (auch wenn sie in Google als "Frei"
        markiert sind), mehrtägige und mehrere gleichzeitig. Termine, die die App selbst
        in den Kalender übertragen hat, lässt der Aufrufer weg (sonst doppelt).

        Returns:
            (Termine je Kalender-ID, Fehlermeldung je Kalender-ID ohne Lesezugriff)

        Kurz zwischengespeichert (GOOGLE_EVENTS_CACHE_SECONDS), damit mehrere
        gleichzeitige Kalenderansichten Google nicht mehrfach fragen.
        """
        ids = sorted({c for c in calendar_ids if c})
        if not self.service or not ids:
            return {}, {}
        ttl = current_app.config.get("GOOGLE_EVENTS_CACHE_SECONDS", 60)
        cache_key = (self.quelle, tuple(ids), isoformat_utc(time_min), isoformat_utc(time_max))
        if ttl:
            with _events_lock:
                treffer = _events_cache.get(cache_key)
                if treffer and treffer[0] > time.monotonic():
                    return treffer[1]
        termine: dict[str, list[dict]] = {}
        fehler: dict[str, str] = {}
        for cal_id in ids:
            try:
                termine[cal_id] = self._events_of_calendar(cal_id, time_min, time_max)
            except Exception as exc:  # noqa: BLE001 - Google darf den Kalender nie blockieren
                status = getattr(getattr(exc, "resp", None), "status", None)
                if status in (403, 404):
                    logger.info("Kein Lesezugriff auf Google-Kalender %s (%s)", cal_id, status)
                    fehler[cal_id] = (
                        "Kein Lesezugriff auf den Google-Kalender (mindestens "
                        "„Alle Termindetails sehen“ nötig)."
                    )
                else:
                    logger.warning("Termine aus %s nicht abrufbar", cal_id, exc_info=True)
                    fehler[cal_id] = "Google ist gerade nicht erreichbar."
        ergebnis = (termine, fehler)
        if ttl:
            with _events_lock:
                if len(_events_cache) > 500:  # Speicher begrenzen
                    _events_cache.clear()
                _events_cache[cache_key] = (time.monotonic() + ttl, ergebnis)
        return ergebnis

    def _events_of_calendar(
        self, calendar_id: str, time_min: datetime, time_max: datetime
    ) -> list[dict]:
        """Alle Termine eines Kalenders (Serien aufgelöst, abgesagte ausgenommen)."""
        termine: list[dict] = []
        seite = None
        for _ in range(_MAX_EVENT_PAGES):
            antwort = (
                self.service.events()
                .list(
                    calendarId=calendar_id,
                    timeMin=isoformat_utc(time_min),
                    timeMax=isoformat_utc(time_max),
                    singleEvents=True,  # Serientermine als einzelne Vorkommen
                    orderBy="startTime",
                    maxResults=250,
                    pageToken=seite,
                )
                .execute()
            )
            for eintrag in antwort.get("items", []):
                termin = _termin_aus_google(eintrag)
                if termin:
                    termine.append(termin)
            seite = antwort.get("nextPageToken")
            if not seite:
                break
        return termine

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
            # Erkennungszeichen: Beim Lesen (list_events) werden diese Termine ausgelassen.
            "extendedProperties": {"private": {APP_MARKER_KEY: "1"}},
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
    """Vergisst gespeicherte Zugangsdaten und gelesene Termine (nach Verbinden/Trennen)."""
    with _credentials_lock:
        _credentials_cache.clear()
    with _events_lock:
        _events_cache.clear()
    if hasattr(_thread_local, "eintrag"):
        del _thread_local.eintrag
