"""Geschäftslogik für die sichere Anlage von Benutzerkonten."""

from typing import Optional, Tuple

from werkzeug.security import generate_password_hash

from app import db
from app.models import AuditLog, Role, User


class UserService:
    """Kapselt Validierung, Persistenz und Auditierung neuer Benutzer."""

    @staticmethod
    def create_user(
        data: dict, actor_id: int
    ) -> Tuple[Optional[User], Optional[str], int]:
        """Legt einen Benutzer transaktionssicher und auditierbar an."""
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
