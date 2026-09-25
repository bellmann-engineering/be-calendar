"""
Termin-Logik: anlegen, ändern, soft-löschen, auflisten.

Wer benutzt sie?
    ``app/routes/event_routes.py`` (Endpunkte unter /api/v1/events).

Womit spricht sie?
    * PostgreSQL: Tabellen ``events``, ``users``, ``customers``, ``audit_logs``
    * NotificationService (In-App + E-Mail an den zugewiesenen Mitarbeiter)
    * google_sync_service (Termin in den Google-Kalender des Mitarbeiters spiegeln,
      ändern, umziehen, löschen)

Wovon hängt sie ab?
    AuthorizationService (wer darf was), app/utils/time.py (UTC-Umrechnung).

Überschneidungen sind ausdrücklich erlaubt: Ein Mitarbeiter kann am selben Tag mehrere
ganztägige und stundenweise Termine haben. Es gibt keine Kollisionsprüfung.
"""

import logging

from sqlalchemy.orm import joinedload

from app import db
from app.models import (
    AuditLog,
    Customer,
    Event,
    RoleEnum,
    User,
)
from app.services.authorization_service import AuthorizationService
from app.services.google_sync_service import synchronisieren
from app.services.notification_service import NotificationService
from app.utils.time import isoformat_utc, parse_iso_datetime, utc_now

logger = logging.getLogger(__name__)

# Rückgabetyp vieler Methoden: (Termin oder None, Fehlermeldung oder None, HTTP-Status)
EventResult = tuple[Event | None, str | None, int]

MAX_TITLE_LENGTH = 200
MAX_LINK_LENGTH = 500


class EventService:
    """Geschäftslogik rund um Kalendertermine."""

    # ------------------------------------------------------------------ Validierung
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

    # ------------------------------------------------------------------ Anlegen
    @staticmethod
    def create_event(data: dict, creator_id: int) -> EventResult:
        """Legt einen Termin an (inkl. Benachrichtigung, Audit-Log, Google-Spiegelung).

        Mitarbeiter sagen nicht zu oder ab – ein Termin ist mit der Zuweisung verbindlich.

        Args:
            data: JSON-Body (title, start_time, end_time, optional assigned_to_id,
                customer_id, meeting_link, is_all_day).
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

        new_event = Event(
            title=data["title"].strip(),
            description=data.get("description") or "",
            start_time=start_time,
            end_time=end_time,
            created_by_id=creator_id,
            assigned_to_id=assigned_to_id,
            is_all_day=data.get("is_all_day", False),
            customer_id=data.get("customer_id"),
            meeting_link=data.get("meeting_link") or None,
        )
        db.session.add(new_event)
        db.session.flush()  # new_event.id wird für das Audit-Log gebraucht

        if assigned_to_id:
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

        previous_values = EventService._audit_snapshot(event)
        assignment_changed = assigned_to_id != event.assigned_to_id

        if "title" in data:
            event.title = data["title"].strip()
        if "description" in data:
            event.description = data.get("description")
        event.start_time = start_time
        event.end_time = end_time
        event.assigned_to_id = assigned_to_id
        if "is_all_day" in data:
            event.is_all_day = data["is_all_day"]
        # "customer_id": null / "meeting_link": null bedeuten bewusst "entfernen".
        if "customer_id" in data:
            event.customer_id = data["customer_id"]
        if "meeting_link" in data:
            event.meeting_link = data["meeting_link"] or None

        if assignment_changed and assigned_to_id is not None:
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
                action="UPDATE_EVENT",
                details_json={
                    "previous": previous_values,
                    "new": EventService._audit_snapshot(event),
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
