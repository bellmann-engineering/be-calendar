"""
Neue Termine im Google-Kalender eines Mitarbeiters erkennen -> Benachrichtigung (Glocke).

Ablauf (``check_user``), ausgelöst beim Abruf der Glocke (GET /api/v1/notifications,
das Frontend fragt jede Minute):
    1. Höchstens alle ``GOOGLE_WATCH_INTERVAL_SECONDS`` pro Mitarbeiter (Standard 3 min).
       ``SELECT … FOR UPDATE SKIP LOCKED`` sorgt dafür, dass bei mehreren Gunicorn-
       Workern immer nur einer gleichzeitig prüft.
    2. Termine der nächsten 60 Tage aus dem zugeordneten Kalender lesen.
    3. Schlüssel (Event-ID bzw. Serien-ID) mit ``google_seen_events`` vergleichen.
       * Erster Abgleich für diesen Kalender: alles nur merken, KEINE Meldungen
         (sonst gäbe es beim Einrichten dutzende Benachrichtigungen).
       * Danach: jeder neue Schlüssel -> Benachrichtigung "Neuer Termin" mit dem Tag
         des Termins (Klick springt im Kalender dorthin). Nur in der App, keine E-Mail.
    Termine, die die App selbst in Google eingetragen hat, zählen nicht (dafür gibt es
    schon "Neuer Termin zugewiesen").

Scheitert Google, passiert einfach nichts – die Glocke funktioniert trotzdem.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

from flask import current_app

from app import db
from app.models import Event, GoogleSeenEvent, User
from app.services.calendar_service import GoogleCalendarService
from app.services.notification_service import NotificationService
from app.utils.time import business_timezone, local_date, utc_now

logger = logging.getLogger(__name__)

_WINDOW_DAYS = 60
# Einträge älter als das können nicht mehr "neu" werden (liegen längst in der Vergangenheit).
_FORGET_AFTER = timedelta(days=180)
_WEEKDAYS = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]


def _start_of(termin: dict) -> tuple[date | None, str]:
    """Tag und lesbare Zeitangabe eines Google-Termins ("Mo, 28.09., 14:00")."""
    start = termin["start"]
    if termin["all_day"]:
        tag = date.fromisoformat(start)
        return tag, f"{_WEEKDAYS[tag.weekday()]}, {tag:%d.%m.}, ganztägig"
    zeitpunkt = datetime.fromisoformat(start.replace("Z", "+00:00")).astimezone(business_timezone())
    return (
        local_date(zeitpunkt),
        f"{_WEEKDAYS[zeitpunkt.weekday()]}, {zeitpunkt:%d.%m., %H:%M} Uhr",
    )


class GoogleWatchService:
    """Abgleich "neue Google-Termine" je Mitarbeiter."""

    @staticmethod
    def check_user(user_id: int) -> int:
        """Prüft den Google-Kalender des Mitarbeiters. Rückgabe: Anzahl neuer Meldungen."""
        try:
            return GoogleWatchService._check(user_id)
        except Exception:  # noqa: BLE001 - die Glocke darf daran nie scheitern
            db.session.rollback()
            logger.warning("Abgleich neuer Google-Termine fehlgeschlagen", exc_info=True)
            return 0

    @staticmethod
    def _check(user_id: int) -> int:
        intervall = current_app.config.get("GOOGLE_WATCH_INTERVAL_SECONDS", 180)
        jetzt = utc_now()
        # Zeile sperren; ist sie schon gesperrt, prüft gerade ein anderer Worker.
        user = (
            db.session.query(User)
            .filter(User.id == user_id)
            .with_for_update(skip_locked=True, of=User)
            .one_or_none()
        )
        if user is None or not user.google_calendar_id:
            db.session.rollback()
            return 0
        if (
            user.google_watch_calendar_id == user.google_calendar_id
            and user.google_watch_checked_at is not None
            and jetzt - user.google_watch_checked_at < timedelta(seconds=intervall)
        ):
            db.session.rollback()
            return 0

        google = GoogleCalendarService()
        if not google.verfuegbar:
            db.session.rollback()
            return 0
        termine, fehler = google.list_events(
            [user.google_calendar_id],
            jetzt - timedelta(days=1),
            jetzt + timedelta(days=_WINDOW_DAYS),
        )
        if user.google_calendar_id in fehler:
            db.session.rollback()
            return 0

        eigene = {
            gid
            for (gid,) in db.session.query(Event.google_event_id).filter(
                Event.google_event_id.isnot(None)
            )
        }
        # Pro Schlüssel das früheste Vorkommen (bei Serien: nächster Termin der Serie).
        aktuelle: dict[str, dict] = {}
        for termin in termine.get(user.google_calendar_id, []):
            if termin["id"] in eigene:
                continue
            schluessel = (termin.get("series_id") or termin["id"])[:300]
            aktuelle.setdefault(schluessel, termin)

        erster_abgleich = user.google_watch_calendar_id != user.google_calendar_id
        if erster_abgleich:
            GoogleSeenEvent.query.filter_by(user_id=user.id).delete()
            bekannt: set[str] = set()
        else:
            bekannt = {
                key
                for (key,) in db.session.query(GoogleSeenEvent.event_key).filter(
                    GoogleSeenEvent.user_id == user.id
                )
            }

        neu = 0
        for schluessel, termin in aktuelle.items():
            if schluessel in bekannt:
                continue
            db.session.add(GoogleSeenEvent(user_id=user.id, event_key=schluessel))
            if erster_abgleich:
                continue
            tag, wann = _start_of(termin)
            serie = " (Serie)" if termin.get("series_id") else ""
            NotificationService.notify_user(
                user_id=user.id,
                title="Neuer Termin im Kalender",
                message=f"{termin['title']}{serie} – {wann}",
                notification_type="GOOGLE_EVENT_NEW",
                target_date=tag,
                send_email=False,
            )
            neu += 1

        GoogleSeenEvent.query.filter(
            GoogleSeenEvent.user_id == user.id,
            GoogleSeenEvent.first_seen_at < jetzt - _FORGET_AFTER,
        ).delete()
        user.google_watch_calendar_id = user.google_calendar_id
        user.google_watch_checked_at = jetzt
        db.session.commit()
        if neu:
            logger.info("%s neue Google-Termine für Benutzer %s gemeldet", neu, user.id)
        return neu
