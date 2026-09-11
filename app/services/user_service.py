from typing import Optional, Tuple, List
from werkzeug.security import generate_password_hash
from app import db
from app.models import AuditLog, Role, User


class UserService:
    @staticmethod
    def create_user(
        data: dict, actor_id: int
    ) -> Tuple[Optional[User], Optional[str], int]:
        email = (data.get("email") or "").strip().lower()
        password = data.get("password")
        role_name = (data.get("role") or "TRAINER").strip().upper()
        first_name = (data.get("first_name") or "").strip()
        last_name = (data.get("last_name") or "").strip()

        if not email or not password or not first_name or not last_name:
            return (
                None,
                "E-Mail, Passwort, Vorname und Nachname sind erforderlich.",
                400,
            )
        if User.query.filter_by(email=email).first():
            return None, f"Die E-Mail {email} ist bereits registriert.", 409
        role = Role.query.filter_by(name=role_name).first()
        if role is None:
            return None, f"Die Rolle '{role_name}' existiert nicht.", 404

        try:
            user = User(
                email=email,
                password_hash=generate_password_hash(password),
                first_name=first_name,
                last_name=last_name,
                role_id=role.id,
                is_active=True,
            )
            db.session.add(user)
            db.session.flush()
            db.session.add(
                AuditLog(
                    user_id=actor_id,
                    action="CREATE_USER",
                    details_json={
                        "created_user_id": user.id,
                        "email": user.email,
                        "role": role.name,
                    },
                )
            )
            db.session.commit()
            return user, None, 201
        except Exception:
            db.session.rollback()
            return None, "Der Benutzer konnte nicht angelegt werden.", 500

    @staticmethod
    def update_user(
        user_id: int, data: dict, actor_id: int
    ) -> Tuple[Optional[User], Optional[str], int]:
        user = db.session.get(User, user_id)
        if not user:
            return None, "Benutzer nicht gefunden.", 404

        email = data.get("email", user.email).strip().lower()
        if email != user.email and User.query.filter_by(email=email).first():
            return None, f"Die E-Mail {email} ist bereits vergeben.", 409

        role_name = data.get("role", user.role.name).strip().upper()
        role = Role.query.filter_by(name=role_name).first()
        if not role:
            return None, f"Die Rolle '{role_name}' existiert nicht.", 404

        user.email = email
        user.first_name = data.get("first_name", user.first_name).strip()
        user.last_name = data.get("last_name", user.last_name).strip()
        user.role_id = role.id

        password = data.get("password")
        if password:
            user.password_hash = generate_password_hash(password)

        db.session.add(
            AuditLog(
                user_id=actor_id,
                action="UPDATE_USER",
                details_json={
                    "updated_user_id": user.id,
                    "email": user.email,
                    "role": role.name,
                },
            )
        )
        try:
            db.session.commit()
            return user, None, 200
        except Exception:
            db.session.rollback()
            return None, "Fehler beim Aktualisieren.", 500

    @staticmethod
    def get_all_users() -> List[dict]:
        users = User.query.order_by(User.first_name).all()
        return [
            {
                "id": u.id,
                "email": u.email,
                "first_name": u.first_name,
                "last_name": u.last_name,
                "role": u.role.name,
                "team_name": u.team.name if u.team else "-",
                "is_active": u.is_active,
                "created_at": u.created_at.isoformat() if u.created_at else None,
                "skill_ids": [s.id for s in u.skills],
            }
            for u in users
        ]

    @staticmethod
    def toggle_status(user_id: int, actor_id: int) -> Tuple[bool, Optional[str], int]:
        user = db.session.get(User, user_id)
        if not user:
            return False, "Benutzer nicht gefunden.", 404
        if user.id == actor_id:
            return False, "Selbst-Deaktivierung blockiert.", 400

        user.is_active = not user.is_active
        db.session.add(
            AuditLog(
                user_id=actor_id,
                action="TOGGLE_USER_STATUS",
                details_json={
                    "target_id": user.id,
                    "new_status": user.is_active,
                    "email": user.email,
                },
            )
        )
        try:
            db.session.commit()
            return True, None, 200
        except Exception:
            db.session.rollback()
            return False, "Datenbankfehler.", 500

    @staticmethod
    def delete_user(target_user_id: int, actor_id: int):
        target_user = db.session.get(User, target_user_id)
        if not target_user:
            return False, "Benutzer nicht gefunden.", 404
        if target_user.id == actor_id:
            return False, "Du kannst dich nicht selbst löschen.", 400

        from app.models import Event, EventRSVP, Team, AuditLog

        if Event.query.filter_by(created_by_id=target_user_id).first():
            return (
                False,
                "Benutzer hat bereits eigene Termine erstellt. Bitte 'Deaktivieren' nutzen.",
                409,
            )

        try:
            Event.query.filter_by(assigned_to_id=target_user_id).update(
                {Event.assigned_to_id: None, Event.reallocation_required: True}
            )
            EventRSVP.query.filter_by(user_id=target_user_id).delete()
            Team.query.filter_by(team_leader_id=target_user_id).update(
                {Team.team_leader_id: None}
            )

            db.session.add(
                AuditLog(
                    user_id=actor_id,
                    action="DELETE_USER",
                    details_json={"deleted_email": target_user.email},
                )
            )

            db.session.delete(target_user)
            db.session.commit()
            return True, None, 200
        except Exception as e:
            db.session.rollback()
            return False, f"Datenbank-Sperre: {str(e)}", 500
