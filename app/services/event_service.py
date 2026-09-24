"""
Termin-Logik: anlegen, ändern, soft-löschen, auflisten, Kollisionen erkennen.

Wer benutzt sie?
    ``app/routes/event_routes.py`` (Endpunkte unter /api/v1/events).

Womit spricht sie?
    * PostgreSQL: Tabellen ``events``, ``event_rsvps``, ``users``, ``customers``, ``audit_logs``
    * NotificationService (In-App + E-Mail an den zugewiesenen Mitarbeiter)
    * GoogleCalendarService (Frei/Belegt prüfen) und google_sync_service (Termin in den
      Google-Kalender des Mitarbeiters spiegeln, ändern, umziehen, löschen)

Wovon hängt sie ab?
    AuthorizationService (wer darf was), app/utils/time.py (UTC-Umrechnung).

Kollisionsprüfung in einem Satz:
    Zwei Termine kollidieren, wenn sich ihre um die Pufferzeiten VERLÄNGERTEN Zeiträume
    überschneiden:  A.start - A.puffer_vorher < B.ende + B.puffer_nachher
                UND A.ende + A.puffer_nachher > B.start - B.puffer_vorher
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import joinedload

from app import db
from app.models import (
    AuditLog,
    Customer,
    Event,
    EventRSVP,
    RoleEnum,
    RSVPStatusEnum,
    User,
)
from app.services.authorization_service import AuthorizationService
from app.services.google_sync_service import synchronisieren
from app.services.notification_service import NotificationService
from app.utils.time import isoformat_utc, parse_iso_datetime, utc_now

logger = logging.getLogger(__name__)

# Rückgabetyp vieler Methoden: (Termin oder None, Fehlermeldung oder None, HTTP-Status)
EventResult = tuple[Event | None, str | None, int]

DEFAULT_BUFFER_MINS = 15
MAX_TITLE_LENGTH = 200
MAX_LINK_LENGTH = 500


@dataclass(frozen=True)
class Conflict:
    """Beschreibt eine gefundene Kollision.

    ``id`` ist None, wenn die Kollision aus dem privaten Google-Kalender stammt
    (dort gibt es keinen Termin in unserer Datenbank).
    """

    id: int | None
    title: str


class EventService:
    """Geschäftslogik rund um Kalendertermine."""

    # ------------------------------------------------------------------ Validierung
    @staticmethod
    def validate_buffers(buffer_before: object, buffer_after: object, role_name: str) -> str | None:
        """Prüft die Pufferzeiten. Gibt eine Fehlermeldung zurück oder None, wenn OK.

        Regeln: ganze Zahlen, nicht negativ; Nicht-CEOs nur 15–30 Minuten.
        """
        # bool ist in Python eine Unterklasse von int (True == 1) -> explizit ausschließen.
        if any(
            isinstance(value, bool) or not isinstance(value, int)
            for value in (buffer_before, buffer_after)
        ):
            return "Pufferzeiten müssen ganze Zahlen sein."
        if buffer_before < 0 or buffer_after < 0:
            return "Pufferzeiten dürfen keine negativen Werte enthalten."
        if role_name != RoleEnum.CEO.value and not (
            15 <= buffer_before <= 30 and 15 <= buffer_after <= 30
        ):
            return "Für Nicht-CEOs müssen Pufferzeiten zwischen 15 und 30 Minuten liegen."
        return None

    @staticmethod
    def _validate_optional_fields(data: dict) -> str | None:
        """Prüft Typen/Längen der optionalen Felder (Titel, Link, Kunde, Ganztägig)."""
        if "title" in data and (
            not isinstance(data["title"], str)
            or not data["title"].strip()
            or len(data["title"].strip()) > MAX_TITLE_LENGTH
        ):
            return f"Der Titel darf nicht leer und höchstens {MAX_TITLE_LENGTH} Zeichen lang sein."
        link = data.get("meeting_link")
        if link is not None and (
            not isinstance(link, str)
            or len(link) > MAX_LINK_LENGTH
            or (link and not link.lower().startswith(("https://", "http://")))
        ):
            return "Der Meeting-Link muss eine http(s)-URL sein."
        customer_id = data.get("customer_id")
        if customer_id is not None:
            if isinstance(customer_id, bool) or not isinstance(customer_id, int):
                return "customer_id muss null oder eine ganze Zahl sein."
            # Früher führte eine unbekannte ID zu einem FK-Fehler + 500 mit SQL im Text.
            if db.session.get(Customer, customer_id) is None:
                return "Der angegebene Kunde existiert nicht."
        if "is_all_day" in data and not isinstance(data["is_all_day"], bool):
            return "is_all_day muss true oder false sein."
        return None

    # ------------------------------------------------------------------ Kollision
    @staticmethod
    def check_conflict(
        assigned_to_id: int | None,
        start_time: datetime,
        end_time: datetime,
        buffer_before: int = 0,
        buffer_after: int = 0,
        exclude_event_id: int | None = None,
    ) -> Conflict | None:
        """Sucht eine Kollision für den Mitarbeiter im angegebenen Zeitraum.

        1. Datenbank: Die komplette Überschneidungsbedingung (inkl. der Puffer der
           BESTEHENDEN Termine) läuft als SQL in PostgreSQL. Früher wurden alle Termine
           des Mitarbeiters geladen und in Python gefiltert – und wegen
           ``not Event.is_deleted`` (Python-``not`` statt SQL) nie ein Treffer gefunden.
        2. Google Calendar: Nur wenn in der DB nichts kollidiert und der Mitarbeiter eine
           ``google_calendar_id`` hinterlegt hat.

        Returns:
            Ein ``Conflict`` oder None, wenn der Zeitraum frei ist.
        """
        if not assigned_to_id:
            return None

        new_effective_start = start_time - timedelta(minutes=buffer_before)
        new_effective_end = end_time + timedelta(minutes=buffer_after)

        # make_interval(mins => n) erzeugt in PostgreSQL ein Intervall von n Minuten.
        existing_before = func.make_interval(
            0, 0, 0, 0, 0, func.coalesce(Event.buffer_before_mins, 0)
        )
        existing_after = func.make_interval(
            0, 0, 0, 0, 0, func.coalesce(Event.buffer_after_mins, 0)
        )

        stmt = (
            select(Event.id, Event.title)
            .where(
                Event.assigned_to_id == assigned_to_id,
                # .is_(False) erzeugt "is_deleted IS false" in SQL. Ein Python-"not" würde
                # hier sofort zu False ausgewertet und die ganze Bedingung zerstören.
                Event.is_deleted.is_(False),
                (Event.start_time - existing_before) < new_effective_end,
                (Event.end_time + existing_after) > new_effective_start,
            )
            .order_by(Event.start_time)
            .limit(1)
        )
        if exclude_event_id:
            stmt = stmt.where(Event.id != exclude_event_id)

        row = db.session.execute(stmt).first()
        if row is not None:
            return Conflict(id=row.id, title=row.title)

        return EventService._check_google_conflict(
            assigned_to_id, new_effective_start, new_effective_end
        )

    @staticmethod
    def _check_google_conflict(
        assigned_to_id: int, effective_start: datetime, effective_end: datetime
    ) -> Conflict | None:
        """Fragt den privaten Google-Kalender (Free/Busy) des Mitarbeiters ab."""
        user = db.session.get(User, assigned_to_id)
        if not user or not user.google_calendar_id:
            return None

        from app.services.calendar_service import GoogleCalendarService

        busy_times = GoogleCalendarService().get_busy_times(
            user.google_calendar_id, effective_start, effective_end
        )
        # Free/Busy liefert nur Blöcke, die den angefragten Zeitraum schneiden -> jeder
        # Eintrag ist eine Kollision.
        if busy_times:
            return Conflict(id=None, title="Privater Termin (Google Kalender)")
        return None

    # ------------------------------------------------------------------ Anlegen
    @staticmethod
    def create_event(data: dict, creator_id: int) -> EventResult:
        """Legt einen Termin an (inkl. RSVP, Benachrichtigung, Audit-Log, Google-Spiegelung).

        Args:
            data: JSON-Body (title, start_time, end_time, optional assigned_to_id,
                buffer_*_mins, customer_id, meeting_link, is_all_day, override_conflict).
            creator_id: ID des eingeloggten Benutzers.
        """
        try:
            start_time = parse_iso_datetime(data.get("start_time"))
            end_time = parse_iso_datetime(data.get("end_time"))
        except ValueError:
            return None, "Ungültiges Datumsformat (ISO-8601 erforderlich).", 400
        if end_time <= start_time:
            return None, "Die Endzeit des Termins muss nach der Startzeit liegen.", 400
        if not isinstance(data.get("title"), str) or not data["title"].strip():
            return None, "Der Titel ist erforderlich.", 400

        creator = db.session.get(User, creator_id)
        if creator is None or not creator.is_active:
            return None, "Der ausführende Benutzer wurde nicht gefunden oder ist nicht aktiv.", 401

        field_error = EventService._validate_optional_fields(data)
        if field_error:
            return None, field_error, 400

        buffer_before = data.get("buffer_before_mins", DEFAULT_BUFFER_MINS)
        buffer_after = data.get("buffer_after_mins", DEFAULT_BUFFER_MINS)
        buffer_error = EventService.validate_buffers(buffer_before, buffer_after, creator.role.name)
        if buffer_error:
            return None, buffer_error, 400

        assigned_to_id = data.get("assigned_to_id")
        assigned_user = None
        if assigned_to_id is not None:
            if isinstance(assigned_to_id, bool) or not isinstance(assigned_to_id, int):
                return None, "assigned_to_id muss null oder eine ganze Zahl sein.", 400
            assigned_user = db.session.get(User, assigned_to_id)
            if not assigned_user:
                return None, f"Benutzer mit ID {assigned_to_id} nicht gefunden.", 404

        allowed, authorization_error = AuthorizationService.can_manage_assignee(
            creator, assigned_user
        )
        if not allowed:
            return None, authorization_error, 403

        conflict = EventService.check_conflict(
            assigned_to_id, start_time, end_time, buffer_before, buffer_after
        )
        is_override = False
        if conflict:
            is_override, override_error = AuthorizationService.can_override_conflict(
                creator, data.get("override_conflict") is True
            )
            if not is_override:
                return (
                    None,
                    f"Kollision mit bestehendem Termin: '{conflict.title}'. {override_error}",
                    409,
                )

        new_event = Event(
            title=data["title"].strip(),
            description=data.get("description") or "",
            start_time=start_time,
            end_time=end_time,
            buffer_before_mins=buffer_before,
            buffer_after_mins=buffer_after,
            created_by_id=creator_id,
            assigned_to_id=assigned_to_id,
            is_all_day=data.get("is_all_day", False),
            customer_id=data.get("customer_id"),
            meeting_link=data.get("meeting_link") or None,
        )
        db.session.add(new_event)
        db.session.flush()  # new_event.id wird für RSVP und Audit-Log gebraucht

        if assigned_to_id:
            db.session.add(
                EventRSVP(
                    event_id=new_event.id,
                    user_id=assigned_to_id,
                    status=RSVPStatusEnum.PENDING.value,
                )
            )
            NotificationService.notify_user(
                user_id=assigned_to_id,
                title="Neuer Termin zugewiesen",
                message=f"Ihnen wurde der Termin '{new_event.title}' zugewiesen.",
                notification_type="EVENT_ASSIGNED",
            )

        db.session.add(
            AuditLog(
                event_id=new_event.id,
                user_id=creator_id,
                action="CREATE_EVENT",
                details_json={
                    "title": new_event.title,
                    "start_time": isoformat_utc(new_event.start_time),
                    "end_time": isoformat_utc(new_event.end_time),
                    "assigned_to_id": assigned_to_id,
                },
            )
        )
        if is_override:
            db.session.add(
                AuditLog(
                    event_id=new_event.id,
                    user_id=creator_id,
                    action="CEO_OVERRIDE_CONFLICT",
                    details_json={
                        "conflicting_event_id": conflict.id,
                        "conflicting_event_title": conflict.title,
                        "override_confirmed": True,
                    },
                )
            )
        db.session.commit()

        # Nach dem Commit: Kopie im Google-Kalender des Mitarbeiters anlegen.
        synchronisieren(new_event)
        return new_event, None, 201

    # ------------------------------------------------------------------ Löschen
    @staticmethod
    def soft_delete_event(event_id: int, user_id: int) -> tuple[bool, str | None, int]:
        """Markiert einen Termin als gelöscht (Soft-Delete) und entfernt die Google-Kopie."""
        # db.session.get() ist der SQLAlchemy-2.0-Weg (Query.get() ist veraltet).
        event = db.session.get(Event, event_id)
        if not event or event.is_deleted:
            return False, "Termin nicht gefunden.", 404

        actor = db.session.get(User, user_id)
        if actor is None or not actor.is_active:
            return False, "Ausführender Benutzer inaktiv.", 401

        allowed, authorization_error = AuthorizationService.can_manage_event(actor, event)
        if not allowed:
            return False, authorization_error, 403

        event.is_deleted = True
        event.deleted_at = utc_now()

        db.session.add(
            AuditLog(
                event_id=event.id,
                user_id=user_id,
                action="DELETE_EVENT",
                details_json={"deleted_at": isoformat_utc(event.deleted_at)},
            )
        )
        db.session.commit()
        # Nach dem Commit: Kopie im Google-Kalender entfernen (Soll-Kalender = keiner).
        synchronisieren(event)
        return True, None, 200

    # ------------------------------------------------------------------ Ändern
    @staticmethod
    def update_event(event_id: int, data: dict, user_id: int) -> EventResult:
        """Ändert einen Termin (Teil-Update: nur mitgeschickte Felder werden geändert)."""
        event = Event.query.filter_by(id=event_id, is_deleted=False).first()
        if event is None:
            return None, "Termin nicht gefunden.", 404

        actor = db.session.get(User, user_id)
        if actor is None or not actor.is_active:
            return None, "Ausführender Benutzer inaktiv.", 401

        allowed, authorization_error = AuthorizationService.can_manage_event(actor, event)
        if not allowed:
            return None, authorization_error, 403

        try:
            start_time = (
                parse_iso_datetime(data["start_time"]) if "start_time" in data else event.start_time
            )
            end_time = (
                parse_iso_datetime(data["end_time"]) if "end_time" in data else event.end_time
            )
        except ValueError:
            return None, "Ungültiges Datumsformat.", 400
        if end_time <= start_time:
            return None, "Endzeit muss nach Startzeit liegen.", 400

        field_error = EventService._validate_optional_fields(data)
        if field_error:
            return None, field_error, 400

        buffer_before = data.get(
            "buffer_before_mins", event.buffer_before_mins or DEFAULT_BUFFER_MINS
        )
        buffer_after = data.get("buffer_after_mins", event.buffer_after_mins or DEFAULT_BUFFER_MINS)
        buffer_error = EventService.validate_buffers(buffer_before, buffer_after, actor.role.name)
        if buffer_error:
            return None, buffer_error, 400

        assigned_to_id = data.get("assigned_to_id", event.assigned_to_id)
        if assigned_to_id is not None:
            if isinstance(assigned_to_id, bool) or not isinstance(assigned_to_id, int):
                return None, "assigned_to_id muss null oder int sein.", 400
            assigned_user = db.session.get(User, assigned_to_id)
            if assigned_user is None:
                return None, "Zugewiesener Benutzer nicht gefunden.", 404
            allowed, authorization_error = AuthorizationService.can_manage_assignee(
                actor, assigned_user
            )
            if not allowed:
                return None, authorization_error, 403
        elif actor.role.name == RoleEnum.TEAM_LEADER.value:
            return None, "Teamleitungen dürfen keinen Termin ohne Teammitglied freigeben.", 403

        conflict = EventService.check_conflict(
            assigned_to_id,
            start_time,
            end_time,
            buffer_before,
            buffer_after,
            exclude_event_id=event.id,
        )
        is_override = False
        if conflict:
            is_override, override_error = AuthorizationService.can_override_conflict(
                actor, data.get("override_conflict") is True
            )
            if not is_override:
                return (
                    None,
                    f"Kollision mit bestehendem Termin: '{conflict.title}'. {override_error}",
                    409,
                )

        previous_values = EventService._audit_snapshot(event)
        assignment_changed = assigned_to_id != event.assigned_to_id

        if "title" in data:
            event.title = data["title"].strip()
        if "description" in data:
            event.description = data.get("description")
        event.start_time = start_time
        event.end_time = end_time
        event.buffer_before_mins = buffer_before
        event.buffer_after_mins = buffer_after
        event.assigned_to_id = assigned_to_id
        if "is_all_day" in data:
            event.is_all_day = data["is_all_day"]
        # "customer_id": null / "meeting_link": null bedeuten bewusst "entfernen".
        if "customer_id" in data:
            event.customer_id = data["customer_id"]
        if "meeting_link" in data:
            event.meeting_link = data["meeting_link"] or None
        event.reallocation_required = assigned_to_id is None

        if assignment_changed and assigned_to_id is not None:
            rsvp = EventRSVP.query.filter_by(event_id=event.id, user_id=assigned_to_id).first()
            if rsvp is None:
                db.session.add(
                    EventRSVP(
                        event_id=event.id,
                        user_id=assigned_to_id,
                        status=RSVPStatusEnum.PENDING.value,
                    )
                )
            else:
                # Erneute Zuweisung an dieselbe Person: alte Antwort zurücksetzen.
                rsvp.status = RSVPStatusEnum.PENDING.value
                rsvp.rejection_reason = None
            NotificationService.notify_user(
                user_id=assigned_to_id,
                title="Neuer Termin",
                message=f"Termin '{event.title}' zugewiesen.",
                notification_type="EVENT_ASSIGNED",
            )

        db.session.add(
            AuditLog(
                event_id=event.id,
                user_id=user_id,
                action="CEO_OVERRIDE_UPDATE" if is_override else "UPDATE_EVENT",
                details_json={
                    "previous": previous_values,
                    "new": EventService._audit_snapshot(event),
                    "conflict_overridden": is_override,
                    "conflicting_event_id": conflict.id if conflict else None,
                },
            )
        )
        db.session.commit()
        # Nach dem Commit: Google-Kopie ändern bzw. bei Neu-Zuweisung umziehen.
        synchronisieren(event)
        return event, None, 200

    @staticmethod
    def _audit_snapshot(event: Event) -> dict:
        """Die für das Audit-Log relevanten Felder eines Termins als JSON-fähiges dict."""
        return {
            "title": event.title,
            "start_time": isoformat_utc(event.start_time),
            "end_time": isoformat_utc(event.end_time),
            "assigned_to_id": event.assigned_to_id,
            "buffer_before_mins": event.buffer_before_mins,
            "buffer_after_mins": event.buffer_after_mins,
            "reallocation_required": event.reallocation_required,
        }

    # ------------------------------------------------------------------ Auflisten
    @staticmethod
    def list_visible_events(
        user_id: int, start_str: str | None = None, end_str: str | None = None
    ) -> tuple[list[Event] | None, str | None, int]:
        """Termine, die der Benutzer sehen darf – optional auf einen Zeitraum begrenzt.

        Sichtbarkeit: CEO/ADMIN alles, TRAINER nur eigene, TEAM_LEADER das eigene Team.

        Performance: ``joinedload(Event.customer)`` holt die Kundenfarbe per JOIN im
        selben SELECT. Früher löste ``e.customer`` in der Route pro Termin eine eigene
        Abfrage aus (N+1).
        """
        actor = db.session.get(User, user_id)
        if actor is None or not actor.is_active:
            return None, "Benutzer nicht gefunden.", 401

        query = Event.query.options(joinedload(Event.customer)).filter(Event.is_deleted.is_(False))
        if start_str or end_str:
            try:
                start_dt = parse_iso_datetime(start_str)
                end_dt = parse_iso_datetime(end_str)
            except ValueError:
                return None, "Ungültiger Zeitraum (start/end im ISO-8601-Format erwartet).", 400
            query = query.filter(Event.end_time >= start_dt, Event.start_time <= end_dt)

        role_name = actor.role.name
        if role_name in {RoleEnum.CEO.value, RoleEnum.ADMIN.value}:
            pass
        elif role_name == RoleEnum.TRAINER.value:
            query = query.filter(Event.assigned_to_id == actor.id)
        elif role_name == RoleEnum.TEAM_LEADER.value:
            if actor.team_id is None:
                return [], None, 200
            query = query.join(User, Event.assigned_to_id == User.id).filter(
                User.team_id == actor.team_id
            )
        else:
            return [], None, 200
        return query.order_by(Event.start_time).all(), None, 200

    @staticmethod
    def latest_rejection_reasons(event_ids: list[int]) -> dict[int, str | None]:
        """Neueste Ablehnungsbegründung je Termin – für ALLE Termine in EINER Abfrage.

        Ersetzt die frühere Einzelabfrage pro Termin in der Schleife (N+1).
        SQL-Idee: pro event_id das jüngste DECLINED-RSVP über eine Unterabfrage mit
        max(updated_at) bestimmen und dagegen joinen.
        """
        if not event_ids:
            return {}
        latest = (
            select(EventRSVP.event_id, func.max(EventRSVP.updated_at).label("max_updated"))
            .where(
                EventRSVP.event_id.in_(event_ids),
                EventRSVP.status == RSVPStatusEnum.DECLINED.value,
            )
            .group_by(EventRSVP.event_id)
            .subquery()
        )
        rows = db.session.execute(
            select(EventRSVP.event_id, EventRSVP.rejection_reason)
            .join(
                latest,
                (EventRSVP.event_id == latest.c.event_id)
                & (EventRSVP.updated_at == latest.c.max_updated),
            )
            .where(EventRSVP.status == RSVPStatusEnum.DECLINED.value)
        ).all()
        return {row.event_id: row.rejection_reason for row in rows}
