"""
Schnittstelle für andere Anwendungen (z. B. die Urlaubsantrags-App).

Was macht diese Datei?
    * ``find_conflicts``: Welche Termine hat eine Person in einem Zeitraum – je Tag?
      Berücksichtigt Termine aus dem Kalender der App UND (falls verbunden) aus dem
      Google-Kalender der Person.
    * ``create_vacation``: Trägt Urlaub als ganztägigen Termin ein – wie "Neuer Termin",
      nur ohne Rollenprüfung (der API-Key ist die Berechtigung): Audit-Log + Spiegelung
      in den Google-Kalender der Person.

Wer benutzt sie?
    ``app/routes/integration_routes.py`` (/api/v1/integration/...).

Datumsangaben: ``start``/``end`` sind Kalendertage der Geschäftszeitzone, BEIDE inklusive
(Urlaub vom 12. bis 14. = drei Tage). ISO-Zeitpunkte mit Uhrzeit werden auf ihren Tag gekürzt.
"""

import logging
from datetime import date, datetime, time, timedelta

from sqlalchemy.orm import joinedload

from app import db
from app.models import AuditLog, Event, User
from app.services.google_sync_service import synchronisieren
from app.utils.time import (
    business_timezone,
    isoformat_utc,
    local_date,
    parse_iso_datetime,
    to_utc,
)

logger = logging.getLogger(__name__)

MAX_RANGE_DAYS = 366
DEFAULT_VACATION_TITLE = "Urlaub"


class IntegrationError(Exception):
    """Fehler mit passendem HTTP-Status und deutscher Meldung für den Aufrufer."""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


def _day(raw: object, name: str) -> date:
    """Kalendertag aus "2026-10-12" oder einem ISO-Zeitpunkt (-> Tag in Ortszeit)."""
    try:
        return local_date(parse_iso_datetime(raw))
    except ValueError as exc:
        raise IntegrationError(f"{name} muss ein Datum im Format JJJJ-MM-TT sein.") from exc


def parse_range(start_raw: object, end_raw: object) -> tuple[date, date]:
    """Prüft den Zeitraum und liefert (erster Tag, letzter Tag), beide inklusive."""
    first, last = _day(start_raw, "start"), _day(end_raw, "end")
    if last < first:
        raise IntegrationError("end darf nicht vor start liegen.")
    if (last - first).days >= MAX_RANGE_DAYS:
        raise IntegrationError(f"Der Zeitraum darf höchstens {MAX_RANGE_DAYS} Tage umfassen.")
    return first, last


def _bounds(first: date, last: date) -> tuple[datetime, datetime]:
    """UTC-Grenzen [Beginn des ersten Tages, Beginn des Tages nach dem letzten)."""
    tz = business_timezone()
    return (
        to_utc(datetime.combine(first, time.min, tzinfo=tz)),
        to_utc(datetime.combine(last + timedelta(days=1), time.min, tzinfo=tz)),
    )


def find_user(email: object) -> User:
    """Aktiven Mitarbeiter zur E-Mail finden (Groß-/Kleinschreibung egal)."""
    if not isinstance(email, str) or not email.strip():
        raise IntegrationError("email ist erforderlich.")
    user = (
        User.query.options(joinedload(User.role))
        .filter(db.func.lower(User.email) == email.strip().lower(), User.is_active.is_(True))
        .first()
    )
    if user is None:
        raise IntegrationError("Kein aktiver Mitarbeiter mit dieser E-Mail.", 404)
    return user


def _days_of(start: datetime, end: datetime, first: date, last: date) -> list[date]:
    """Alle Kalendertage von [start, end) (Ende exklusiv), auf den Zeitraum beschnitten."""
    begin = local_date(start)
    # Ende ist exklusiv: ein Termin bis 00:00 Uhr gehört nicht mehr zum nächsten Tag.
    stop = local_date(end - timedelta(microseconds=1)) if end > start else begin
    day, days = max(begin, first), []
    while day <= min(stop, last):
        days.append(day)
        day += timedelta(days=1)
    return days


def _google_events(user: User, start: datetime, end: datetime) -> list[dict]:
    """Termine aus dem Google-Kalender der Person (leer, wenn nicht verbunden/erreichbar)."""
    if not user.google_calendar_id:
        return []
    from app.services.calendar_service import GoogleCalendarService

    google = GoogleCalendarService()
    if not google.verfuegbar:
        return []
    termine, fehler = google.list_events([user.google_calendar_id], start, end)
    if user.google_calendar_id in fehler:
        logger.warning("Google-Termine von %s nicht lesbar: %s", user.email, fehler)
    eigene = {
        gid
        for (gid,) in db.session.query(Event.google_event_id).filter(
            Event.google_event_id.isnot(None)
        )
    }
    return [t for t in termine.get(user.google_calendar_id, []) if t["id"] not in eigene]


def find_conflicts(user: User, first: date, last: date) -> list[dict]:
    """Termine der Person im Zeitraum, gruppiert nach Tag (aufsteigend). Leer = frei."""
    start, end = _bounds(first, last)
    items: list[tuple[datetime, datetime, dict]] = []

    events = (
        Event.query.filter(
            Event.assigned_to_id == user.id,
            Event.is_deleted.is_(False),
            Event.end_time > start,
            Event.start_time < end,
        )
        .order_by(Event.start_time)
        .all()
    )
    for e in events:
        items.append(
            (
                e.start_time,
                e.end_time,
                {
                    "title": e.title,
                    "start_time": isoformat_utc(e.start_time),
                    "end_time": isoformat_utc(e.end_time),
                    "is_all_day": e.is_all_day,
                    "source": "calendar",
                },
            )
        )
    for g in _google_events(user, start, end):
        g_start, g_end = (
            to_utc(parse_iso_datetime(g["start"])),
            to_utc(parse_iso_datetime(g["end"])),
        )
        items.append(
            (
                g_start,
                g_end,
                {
                    "title": g["title"],
                    "start_time": isoformat_utc(g_start),
                    "end_time": isoformat_utc(g_end),
                    "is_all_day": g["all_day"],
                    "source": "google",
                },
            )
        )

    by_day: dict[date, list[dict]] = {}
    for item_start, item_end, payload in sorted(items, key=lambda i: i[0]):
        for day in _days_of(item_start, item_end, first, last):
            by_day.setdefault(day, []).append(payload)
    return [{"date": d.isoformat(), "events": by_day[d]} for d in sorted(by_day)]


def create_vacation(user: User, first: date, last: date, data: dict) -> Event:
    """Legt Urlaub als ganztägigen Termin der Person an (Ende exklusiv wie im Kalender)."""
    title = data.get("title", DEFAULT_VACATION_TITLE)
    description = data.get("description")
    if not isinstance(title, str) or not title.strip() or len(title.strip()) > 200:
        raise IntegrationError("title darf nicht leer und höchstens 200 Zeichen lang sein.")
    if description is not None and not isinstance(description, str):
        raise IntegrationError("description muss ein Text sein.")

    start, end = _bounds(first, last)
    event = Event(
        title=title.strip(),
        description=description or "",
        start_time=start,
        end_time=end,
        is_all_day=True,
        created_by_id=user.id,
        assigned_to_id=user.id,
    )
    db.session.add(event)
    db.session.flush()  # event.id für das Audit-Log
    db.session.add(
        AuditLog(
            event_id=event.id,
            user_id=user.id,
            action="CREATE_EVENT",
            details_json={
                "title": event.title,
                "start_time": isoformat_utc(event.start_time),
                "end_time": isoformat_utc(event.end_time),
                "assigned_to_id": user.id,
                "source": "integration-api",
            },
        )
    )
    db.session.commit()
    synchronisieren(event)  # nach dem Commit: Kopie in den Google-Kalender der Person
    return event
