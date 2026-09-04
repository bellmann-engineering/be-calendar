"""Verwaltungslogik für Rollen, Rechteentzug und Bereinigungs-Reports."""

from typing import Dict, Any, Tuple
from app import db
from app.models import User, Role, Team, Event, AuditLog
from app.services.notification_service import NotificationService


class AdminService:

    @staticmethod
    def revoke_team_leader_role(
        user_id: int, executed_by_id: int
    ) -> Tuple[Dict[str, Any], int]:
        """Entzieht die Team-Leader-Rolle, baut Teamzuweisungen ab und sendet einen Report an Kai Bellmann."""
        target_user = db.session.get(User, user_id)
        if not target_user:
            return {"error": "Benutzer nicht gefunden."}, 404

        managed_teams = Team.query.filter_by(team_leader_id=user_id).all()

        affected_events = Event.query.filter(
            Event.created_by_id == user_id, not Event.is_deleted
        ).all()

        for team in managed_teams:
            team.team_leader_id = None

        trainer_role = Role.query.filter_by(name="TRAINER").first()
        if trainer_role:
            target_user.role_id = trainer_role.id

        report_data = {
            "revoked_user_id": target_user.id,
            "revoked_user_email": target_user.email,
            "unassigned_team_count": len(managed_teams),
            "managed_team_names": [t.name for t in managed_teams],
            "open_events_count": len(affected_events),
        }

        ceo_role = Role.query.filter_by(name="CEO").first()
        ceo_user = (
            User.query.filter_by(role_id=ceo_role.id).first() if ceo_role else None
        )

        if ceo_user:
            NotificationService.notify_user(
                user_id=ceo_user.id,
                title="Rechteentzug-Report: Team Leader zurückgestuft",
                message=(
                    f"Dem Benutzer {target_user.first_name} {target_user.last_name} wurden die TL-Rechte entzogen. "
                    f"Betroffene Teams: {len(managed_teams)}, Offene Termine zur Überprüfung: {len(affected_events)}."
                ),
                notification_type="TL_REVOCATION_REPORT",  # <--- Hier wieder eingefügt
            )

        audit = AuditLog(
            user_id=executed_by_id,
            action="REVOKE_TL_ROLE_REPORT_GENERATED",
            details_json=report_data,
        )
        db.session.add(audit)
        db.session.commit()

        return {
            "message": "TL-Rechte erfolgreich entzogen. Report an CEO gesendet.",
            "report": report_data,
        }, 200
