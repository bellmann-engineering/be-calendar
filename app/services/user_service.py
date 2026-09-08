from typing import Optional, Tuple, List
import csv
import io
import secrets
from werkzeug.security import generate_password_hash
from app import db
from app.models import AuditLog, Role, User
from app.services.email_service import EmailService


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
    def import_csv(file, actor_id: int) -> Tuple[dict, int]:
        try:
            stream = io.StringIO(file.stream.read().decode("UTF8"), newline=None)
            reader = csv.DictReader(stream)
        except Exception:
            return {
                "error": "Konnte die Datei nicht lesen. Bitte UTF-8 CSV verwenden."
            }, 400

        roles_cache = {r.name: r for r in Role.query.all()}
        success_count, errors = 0, []

        for row_idx, row in enumerate(reader, start=1):
            email = (row.get("email") or "").strip().lower()
            first_name = (row.get("first_name") or "").strip()
            last_name = (row.get("last_name") or "").strip()
            role_name = (row.get("role") or "TRAINER").strip().upper()

            if not email or not first_name or not last_name:
                errors.append(f"Zeile {row_idx}: Pflichtfelder fehlen.")
                continue
            if User.query.filter_by(email=email).first():
                errors.append(f"Zeile {row_idx}: E-Mail {email} existiert bereits.")
                continue
            role = roles_cache.get(role_name)
            if not role:
                errors.append(f"Zeile {row_idx}: Rolle '{role_name}' ungültig.")
                continue

            raw_password = secrets.token_urlsafe(8)
            user = User(
                email=email,
                password_hash=generate_password_hash(raw_password),
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
                    action="IMPORT_USER_CSV",
                    details_json={
                        "created_id": user.id,
                        "email": email,
                        "role": role.name,
                    },
                )
            )

            try:
                msg = f"Hallo {first_name},\n\ndein Account ist bereit.\nLogin: {email}\nPasswort: {raw_password}\n\nViele Grüße!"
                EmailService.send_email(email, "Dein Bellmann Calendar Account", msg)
            except Exception:
                pass

            success_count += 1

        try:
            db.session.commit()
            return {
                "message": f"Import fertig. {success_count} Benutzer erstellt.",
                "errors": errors,
            }, 200
        except Exception as e:
            db.session.rollback()
            return {"error": f"Datenbankfehler: {str(e)}"}, 500
