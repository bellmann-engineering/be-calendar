from typing import Dict, Any, Tuple
from app import db
from app.models import User, Role, Team, AuditLog


class AdminService:
    @staticmethod
    def revoke_elevated_role(
        user_id: int, executed_by_id: int
    ) -> Tuple[Dict[str, Any], int]:
        target_user = db.session.get(User, user_id)
        actor = db.session.get(User, executed_by_id)

        if not target_user or not actor:
            return {"error": "Benutzer nicht gefunden."}, 404

        # Hierarchie-Prüfung
        if actor.role.name not in ["CEO", "ADMIN"]:
            return {"error": "Fehlende Berechtigung."}, 403

        if target_user.role.name == "CEO":
            return {"error": "Dem CEO können keine Rechte entzogen werden."}, 403

        if actor.role.name == "ADMIN" and target_user.role.name == "ADMIN":
            return {
                "error": "Ein Admin kann einem anderen Admin keine Rechte entziehen."
            }, 403

        old_role = target_user.role.name
        trainer_role = Role.query.filter_by(name="TRAINER").first()

        if old_role == "TRAINER":
            return {"error": "Der Benutzer ist bereits ein regulärer Trainer."}, 400

        # Rolle physisch zurücksetzen
        target_user.role_id = trainer_role.id

        # Wenn er Team Leader war, Teams freigeben
        managed_teams = Team.query.filter_by(team_leader_id=user_id).all()
        for team in managed_teams:
            team.team_leader_id = None

        db.session.add(
            AuditLog(
                user_id=executed_by_id,
                action=f"REVOKE_{old_role}_ROLE",
                details_json={
                    "revoked_user_id": target_user.id,
                    "old_role": old_role,
                    "new_role": "TRAINER",
                },
            )
        )

        db.session.commit()

        return {
            "message": f"Rechte ({old_role}) erfolgreich entzogen. Der Benutzer ist nun wieder TRAINER."
        }, 200
