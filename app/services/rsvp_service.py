"""Geschäftslogik für Rückmeldungen zu Termineinladungen."""

from __future__ import annotations

from typing import Optional, Tuple

from app import db
from app.models import AuditLog, Event, EventRSVP, RSVPStatusEnum, Team, User
from app.services.notification_service import NotificationService


class RSVPService:
    """Kapselt Validierung, Aktualisierung und Auditierung von RSVPs."""

    @staticmethod
    def update_rsvp(
        event_id: int,
        user_id: int,
        status: str,
        rejection_reason: Optional[str] = None,
    ) -> Tuple[Optional[EventRSVP], Optional[str], int]:
        """Aktualisiert die Rückmeldung eines eingeladenen Benutzers."""
        try:
            normalized_status = status.strip().upper()
        except AttributeError:
            return None, "Der RSVP-Status muss als Text angegeben werden.", 400

        allowed_statuses = {
            RSVPStatusEnum.ACCEPTED.value,
            RSVPStatusEnum.DECLINED.value,
            RSVPStatusEnum.TENTATIVE.value,
        }
        if normalized_status not in allowed_statuses:
            values = ", ".join(sorted(allowed_statuses))
            return None, f"Ungültiger RSVP-Status. Erlaubt sind: {values}.", 400

        event = db.session.get(Event, event_id)
        if event is None or event.is_deleted:
            return None, "Termin nicht gefunden.", 404

        rsvp = EventRSVP.query.filter_by(event_id=event_id, user_id=user_id).first()
        if rsvp is None:
            return None, "Für diesen Benutzer liegt keine Termineinladung vor.", 403
        if event.assigned_to_id != user_id:
            return (
                None,
                "Diese Einladung ist nicht mehr aktiv und kann nicht beantwortet werden.",
                409,
            )

        cleaned_reason = (rejection_reason or "").strip()
        if normalized_status == RSVPStatusEnum.DECLINED.value and not cleaned_reason:
            return None, "Für eine Ablehnung ist eine Begründung erforderlich.", 400

        previous_status = rsvp.status
        rsvp.status = normalized_status
        rsvp.rejection_reason = (
            cleaned_reason
            if normalized_status == RSVPStatusEnum.DECLINED.value
            else None
        )

        # In RSVPService.update_rsvp bei status == 'DECLINED':
        reallocation_required = normalized_status == RSVPStatusEnum.DECLINED.value
        if reallocation_required:
            event.assigned_to_id = None
            event.reallocation_required = True

            leader_id = event.created_by_id
            creator = db.session.get(User, event.created_by_id)
            if creator and creator.team_id:
                team = db.session.get(Team, creator.team_id)
                if team and team.team_leader_id:
                    leader_id = team.team_leader_id

            # Aufgabe direkt an den TL übermitteln
            NotificationService.notify_user(
                user_id=leader_id,
                title="Aufgabe: Neue Zuordnung erforderlich",
                message=f"Der Termin '{event.title}' wurde abgelehnt. Begründung: '{rsvp.rejection_reason}'. Bitte neu zuweisen.",
                notification_type="TASK_REALLOCATION_NEEDED",
            )

            try:
                NotificationService.notify_user(
                    user_id=leader_id,
                    title="Termin abgelehnt – Neu-Zuweisung erforderlich",
                    message=f"Der Termin '{event.title}' wurde abgelehnt. Begründung: {rsvp.rejection_reason}",
                    notification_type="REALLOCATION_REQUIRED",
                )
            except Exception:
                pass

        audit = AuditLog(
            event_id=event.id,
            user_id=user_id,
            action=(
                "RSVP_DECLINED_REALLOCATION_NEEDED"
                if reallocation_required
                else "UPDATE_RSVP"
            ),
            details_json={
                "previous_status": previous_status,
                "new_status": normalized_status,
                "rejection_reason": rsvp.rejection_reason,
                "reallocation_required": reallocation_required,
            },
        )
        db.session.add(audit)

        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            return (
                None,
                f"Die RSVP-Rückmeldung konnte nicht gespeichert werden: {str(e)}",
                500,
            )

        return rsvp, None, 200

    @staticmethod
    def get_rsvp(
        event_id: int, user_id: int
    ) -> Tuple[Optional[EventRSVP], Optional[str], int]:
        """Liest die persönliche Rückmeldung eines eingeladenen Benutzers aus."""
        event = db.session.get(Event, event_id)
        if event is None or event.is_deleted:
            return None, "Termin nicht gefunden.", 404

        rsvp = EventRSVP.query.filter_by(event_id=event_id, user_id=user_id).first()
        if rsvp is None:
            return None, "Für diesen Benutzer liegt keine Termineinladung vor.", 404

        return rsvp, None, 200
