"""
Administrative Sonderaktionen: erhöhte Rechte entziehen (zurück auf TRAINER).

Wer benutzt sie?
    ``app/routes/auth_routes.py`` -> PUT /api/v1/auth/users/<id>/revoke-role
    (und der ältere Alias .../revoke-tl).

Regeln (an AuthorizationService.can_manage_user angelehnt):
    * Nur CEO und ADMIN.
    * Dem CEO kann niemand Rechte entziehen; ein ADMIN keinem anderen ADMIN.
    * Ist die Person Teamleitung, werden ihre Teams "führungslos" (team_leader_id = NULL).

Wirkung: Sofort, weil app/security.py die Rolle bei jedem Request aus der DB liest.
"""

import logging

from app import db
from app.models import AuditLog, Role, RoleEnum, Team, User
from app.services.authorization_service import AuthorizationService

logger = logging.getLogger(__name__)


class AdminService:
    """Rechteverwaltung für CEO und ADMIN."""

    @staticmethod
    def revoke_elevated_role(user_id: int, executed_by_id: int) -> tuple[dict, int]:
        """Stuft ``user_id`` auf TRAINER herab. Liefert (JSON-Antwort, HTTP-Status)."""
        target_user = db.session.get(User, user_id)
        actor = db.session.get(User, executed_by_id)
        if not target_user or not actor:
            return {"error": "Benutzer nicht gefunden."}, 404

        if target_user.role.name == RoleEnum.CEO.value:
            return {"error": "Dem CEO können keine Rechte entzogen werden."}, 403
        allowed, error = AuthorizationService.can_manage_user(
            actor, target_user, RoleEnum.TRAINER.value
        )
        if not allowed:
            return {"error": error}, 403

        old_role = target_user.role.name
        if old_role == RoleEnum.TRAINER.value:
            return {"error": "Der Benutzer ist bereits ein regulärer Trainer."}, 400

        trainer_role = Role.query.filter_by(name=RoleEnum.TRAINER.value).first()
        if trainer_role is None:
            logger.error("Rolle TRAINER fehlt – wurde seed.py ausgeführt?")
            return {"error": "Rolle TRAINER ist nicht angelegt."}, 500
        target_user.role_id = trainer_role.id

        # War die Person Teamleitung, werden ihre Teams freigegeben.
        Team.query.filter_by(team_leader_id=user_id).update({Team.team_leader_id: None})

        db.session.add(
            AuditLog(
                user_id=executed_by_id,
                action=f"REVOKE_{old_role}_ROLE",
                details_json={
                    "revoked_user_id": target_user.id,
                    "old_role": old_role,
                    "new_role": RoleEnum.TRAINER.value,
                },
            )
        )
        db.session.commit()
        return {
            "message": f"Rechte ({old_role}) erfolgreich entzogen. Der Benutzer ist nun wieder TRAINER."
        }, 200

    @staticmethod
    def revoke_team_leader_role(user_id: int, executed_by_id: int) -> tuple[dict, int]:
        """Alias für ältere Frontend-Aufrufe (/revoke-tl) – identisch zu revoke_elevated_role."""
        return AdminService.revoke_elevated_role(user_id, executed_by_id)
