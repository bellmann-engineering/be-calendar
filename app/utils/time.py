"""
Zeitzonen-Hilfsfunktionen – die EINZIGE Stelle, an der Datumswerte umgerechnet werden.

Grundregel des Projekts:
    * In PostgreSQL wird jeder Zeitpunkt als ``timestamptz`` gespeichert (intern UTC).
    * In Python arbeiten wir ausschließlich mit "aware" ``datetime``-Objekten in UTC.
    * Nach außen (JSON-API) geben wir ISO-8601 MIT Offset aus, z. B.
      ``2026-09-25T08:00:00+00:00``. Der Browser (FullCalendar) rechnet das selbst in
      die lokale Zeit des Benutzers um.
    * ``datetime.utcnow()`` ist verboten (liefert "naive" Werte) -> ``utc_now()`` nutzen.

Wer benutzt diese Datei?
    Services (event_service, rsvp_service, ...), Routen (Serialisierung) und Models
    (Default-Werte für created_at & Co.).

Wovon hängt sie ab?
    Nur von der Standardbibliothek (``datetime``, ``zoneinfo``) sowie – optional – von
    ``flask.current_app`` für die konfigurierte Geschäftszeitzone (APP_TIMEZONE).
    Das pip-Paket ``tzdata`` liefert die Zeitzonendatenbank im schlanken Docker-Image.
"""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from flask import current_app, has_app_context

# Fallback, falls außerhalb eines Flask-Kontexts aufgerufen (z. B. in Skripten).
_DEFAULT_TZ = "Europe/Berlin"


def utc_now() -> datetime:
    """Aktueller Zeitpunkt als zeitzonenbewusstes UTC-Datum (Ersatz für utcnow())."""
    return datetime.now(timezone.utc)


def business_timezone() -> ZoneInfo:
    """Liefert die Geschäftszeitzone aus der Konfiguration (Standard: Europe/Berlin)."""
    name = _DEFAULT_TZ
    if has_app_context():
        name = current_app.config.get("APP_TIMEZONE", _DEFAULT_TZ)
    return ZoneInfo(name)


def to_utc(value: datetime | None) -> datetime | None:
    """Wandelt ein beliebiges datetime in ein "aware" UTC-datetime um.

    * Aware-Werte (mit Offset) werden einfach nach UTC umgerechnet.
    * Naive Werte (ohne Offset) werden als Ortszeit der Geschäftszeitzone verstanden.
      Grund: Ein Formularwert wie "2026-09-25T10:00" meint 10 Uhr deutscher Zeit.
    """
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=business_timezone())
    return value.astimezone(timezone.utc)


def parse_iso_datetime(raw: object) -> datetime:
    """Parst einen ISO-8601-String aus einem Request und liefert UTC (aware).

    Akzeptiert "Z" (UTC), Offsets wie "+02:00" und naive Werte (-> Geschäftszeitzone).

    Raises:
        ValueError: Wenn ``raw`` kein String ist oder kein gültiges ISO-Datum enthält.
    """
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("Datum muss ein nicht-leerer ISO-8601-String sein.")
    # Python < 3.11 kannte kein "Z"; replace() hält den Code robust und explizit.
    parsed = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
    return to_utc(parsed)


def isoformat_utc(value: datetime | None) -> str | None:
    """Serialisiert ein datetime für die API (immer UTC mit "+00:00") oder None."""
    if value is None:
        return None
    return to_utc(value).isoformat()
