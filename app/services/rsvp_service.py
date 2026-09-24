"""
Geschäftslogik für Rückmeldungen (RSVP) zu Termineinladungen.

Ablauf einer Ablehnung (DECLINED):
    1. Trainer lehnt mit Pflicht-Begründung ab (PUT /api/v1/events/<id>/rsvp).
    2. Termin verliert seine Zuweisung und wird mit ``reallocation_required=True`` markiert
       (im Kalender rot).
    3. Die zuständige Teamleitung (sonst der Ersteller) erhält EINE Benachrichtigung
       (+ E-Mail nach dem Commit).
    4. Audit-Log-Eintrag.

Wer benutzt sie?
    ``app/routes/rsvp_routes.py``.

Womit spricht sie?
    Tabellen ``event_rsvps``, ``events``, ``users``, ``teams``, ``audit_logs`` sowie
    NotificationService.
"""

from __future__ import annotations

import logging

from app import db
from app.models import AuditLog, Event, EventRSVP, RSVPStatusEnum, Team, User
from app.services.google_sync_service import synchronisieren
from app.services.notification_service import NotificationService

logger = logging.getLogger(__name__)

RSVPResult = tuple[EventRSVP | None, str | None, int]
MAX_REASON_LENGTH = 2000


class RSVPService:
    """Kapselt Validierung, Aktualisierung und Auditierung von RSVPs."""

    @staticmethod
    def update_rsvp(
        event_id: int,
        user_id: int,
        status: str | None,
        rejection_reason: str | None = None,
    ) -> RSVPResult:
        """Aktualisiert die Rückmeldung eines eingeladenen Benutzers."""
        if not isinstance(status, str):
            return None, "Der RSVP-Status muss als Text angegeben werden.", 400
        normalized_status = status.strip().upper()

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

        cleaned_reason = (
            (rejection_reason or "").strip() if isinstance(rejection_reason, str) else ""
        )
        if normalized_status == RSVPStatusEnum.DECLINED.value and not cleaned_reason:
            return None, "Für eine Ablehnung ist eine Begründung erforderlich.", 400
        if len(cleaned_reason) > MAX_REASON_LENGTH:
            return (
                None,
                f"Die Begründung darf höchstens {MAX_REASON_LENGTH} Zeichen lang sein.",
                400,
            )

        previous_status = rsvp.status
        rsvp.status = normalized_status
        rsvp.rejection_reason = (
            cleaned_reason if normalized_status == RSVPStatusEnum.DECLINED.value else None
        )

        reallocation_required = normalized_status == RSVPStatusEnum.DECLINED.value
        if reallocation_required:
            event.assigned_to_id = None
            event.reallocation_required = True
            # Früher wurden hier ZWEI fast identische Benachrichtigungen (+ zwei Mails)
            # an dieselbe Person geschickt – jetzt genau eine.
            NotificationService.notify_user(
                user_id=RSVPService._responsible_leader_id(event),
                title="Termin abgelehnt – Neu-Zuweisung erforderlich",
                message=(
                    f"Der Termin '{event.title}' wurde abgelehnt. "
                    f"Begründung: {rsvp.rejection_reason}. Bitte neu zuweisen."
                ),
                notification_type="REALLOCATION_REQUIRED",
            )

        db.session.add(
            AuditLog(
                event_id=event.id,
                user_id=user_id,
                action=(
                    "RSVP_DECLINED_REALLOCATION_NEEDED" if reallocation_required else "UPDATE_RSVP"
                ),
                details_json={
                    "previous_status": previous_status,
                    "new_status": normalized_status,
                    "rejection_reason": rsvp.rejection_reason,
                    "reallocation_required": reallocation_required,
                },
            )
        )
        db.session.commit()
        if reallocation_required:
            # Nach dem Commit: Der Termin gehört niemandem mehr -> Kopie aus dem
            # Google-Kalender des absagenden Trainers entfernen.
            synchronisieren(event)
        return rsvp, None, 200

    @staticmethod
    def _responsible_leader_id(event: Event) -> int:
        """Wer muss neu zuweisen? Die Teamleitung des Erstellers, sonst der Ersteller selbst."""
        creator = db.session.get(User, event.created_by_id)
        if creator and creator.team_id:
            team = db.session.get(Team, creator.team_id)
            if team and team.team_leader_id:
                return team.team_leader_id
        return event.created_by_id

    @staticmethod
    def get_rsvp(event_id: int, user_id: int) -> RSVPResult:
        """Liest die persönliche Rückmeldung eines eingeladenen Benutzers aus."""
        event = db.session.get(Event, event_id)
        if event is None or event.is_deleted:
            return None, "Termin nicht gefunden.", 404

        rsvp = EventRSVP.query.filter_by(event_id=event_id, user_id=user_id).first()
        if rsvp is None:
            return None, "Für diesen Benutzer liegt keine Termineinladung vor.", 404
        return rsvp, None, 200
