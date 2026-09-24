"""
Benutzerverwaltung: anlegen, ändern, auflisten, sperren, löschen, CSV-Massenimport.

Wer benutzt sie?
    ``app/routes/auth_routes.py`` (Endpunkte unter /api/v1/auth/...). Die Seite
    "Mitarbeiter" (members.html) ruft diese Endpunkte auf.

Womit spricht sie?
    Tabellen ``users``, ``roles``, ``events``, ``event_rsvps``, ``teams``, ``audit_logs``;
    beim CSV-Import zusätzlich den SMTP-Server (Einladungs-Mail mit Passwort-Link).

Sicherheitsregeln:
    Jede verändernde Methode fragt ``AuthorizationService.can_manage_user`` –
    dadurch kann z. B. ein ADMIN weder den CEO bearbeiten noch sich selbst befördern.
"""

import csv
import io
import logging

from flask import render_template
from sqlalchemy.orm import joinedload
from werkzeug.datastructures import FileStorage
from werkzeug.security import generate_password_hash

from app import db
from app.models import AuditLog, Event, EventRSVP, Role, RoleEnum, Team, User
from app.services.auth_service import PURPOSE_INVITE, AuthService
from app.services.authorization_service import AuthorizationService
from app.services.email_service import EmailService

logger = logging.getLogger(__name__)


_KEIN_WERT = object()


def _kalender_id(data: dict) -> tuple[object, str | None]:
    """Liest ``google_calendar_id`` aus dem Request.

    Rückgabe: (wert, fehler). ``_KEIN_WERT`` = Feld nicht mitgeschickt (nichts ändern),
    ``None`` = Zuordnung entfernen, sonst die bereinigte Kalender-ID.
    Eine Kalender-ID ist z. B. eine Gmail-Adresse oder "…@group.calendar.google.com".
    """
    if "google_calendar_id" not in data:
        return _KEIN_WERT, None
    wert = data.get("google_calendar_id")
    if wert is None or (isinstance(wert, str) and not wert.strip()):
        return None, None
    if (
        not isinstance(wert, str)
        or len(wert.strip()) > 255
        or any(c.isspace() for c in wert.strip())
    ):
        return _KEIN_WERT, "Ungültige Google-Kalender-ID (max. 255 Zeichen, keine Leerzeichen)."
    return wert.strip(), None


class UserService:
    """Kapselt alle Anwendungsfälle rund um Benutzerkonten."""

    @staticmethod
    def create_user(data: dict, actor_id: int) -> tuple[User | None, str | None, int]:
        """Legt einen Benutzer mit vom Admin gesetztem Passwort an.

        Args:
            data: JSON-Body mit email, password, first_name, last_name, role.
            actor_id: ID des eingeloggten CEO/ADMIN.
        """
        email = (data.get("email") or "").strip().lower()
        password = data.get("password")
        role_name = (data.get("role") or RoleEnum.TRAINER.value).strip().upper()
        first_name = (data.get("first_name") or "").strip()
        last_name = (data.get("last_name") or "").strip()

        if not email or not password or not first_name or not last_name:
            return (
                None,
                "E-Mail, Passwort, Vorname und Nachname sind erforderlich.",
                400,
            )
        password_error = AuthService.validate_password(password)
        if password_error:
            return None, password_error, 400
        kalender, kalender_fehler = _kalender_id(data)
        if kalender_fehler:
            return None, kalender_fehler, 400

        actor = db.session.get(User, actor_id)
        allowed, error = AuthorizationService.can_manage_user(actor, None, role_name)
        if not allowed:
            return None, error, 403

        if User.query.filter_by(email=email).first():
            return None, f"Die E-Mail {email} ist bereits registriert.", 409
        role = Role.query.filter_by(name=role_name).first()
        if role is None:
            return None, f"Die Rolle '{role_name}' existiert nicht.", 404

        user = User(
            email=email,
            password_hash=generate_password_hash(password),
            first_name=first_name,
            last_name=last_name,
            role_id=role.id,
            is_active=True,
            google_calendar_id=None if kalender is _KEIN_WERT else kalender,
        )
        db.session.add(user)
        # flush() schickt das INSERT an die DB (ohne Commit), damit user.id bekannt ist.
        db.session.flush()
        db.session.add(
            AuditLog(
                user_id=actor_id,
                action="CREATE_USER",
                details_json={"created_user_id": user.id, "email": user.email, "role": role.name},
            )
        )
        db.session.commit()
        return user, None, 201

    @staticmethod
    def update_user(user_id: int, data: dict, actor_id: int) -> tuple[User | None, str | None, int]:
        """Ändert Stammdaten, Rolle und optional das Passwort eines Benutzers."""
        user = db.session.get(User, user_id)
        if not user:
            return None, "Benutzer nicht gefunden.", 404

        email = str(data.get("email", user.email)).strip().lower()
        role_name = str(data.get("role", user.role.name)).strip().upper()

        actor = db.session.get(User, actor_id)
        # Rolle nur prüfen, wenn sie sich tatsächlich ändert (oder Self-Edit).
        allowed, error = AuthorizationService.can_manage_user(actor, user, role_name)
        if not allowed:
            return None, error, 403

        if email != user.email and User.query.filter_by(email=email).first():
            return None, f"Die E-Mail {email} ist bereits vergeben.", 409
        role = Role.query.filter_by(name=role_name).first()
        if not role:
            return None, f"Die Rolle '{role_name}' existiert nicht.", 404

        kalender, kalender_fehler = _kalender_id(data)
        if kalender_fehler:
            return None, kalender_fehler, 400

        password = data.get("password")
        if password:
            password_error = AuthService.validate_password(password)
            if password_error:
                return None, password_error, 400
            user.password_hash = generate_password_hash(password)

        user.email = email
        user.first_name = str(data.get("first_name", user.first_name)).strip()
        user.last_name = str(data.get("last_name", user.last_name)).strip()
        user.role_id = role.id
        kalender_geaendert = kalender is not _KEIN_WERT and kalender != user.google_calendar_id
        if kalender_geaendert:
            # Hinweis: Bereits gespiegelte Termine bleiben im alten Kalender, bis sie das
            # nächste Mal geändert werden – dann zieht google_sync_service sie automatisch um.
            user.google_calendar_id = kalender

        db.session.add(
            AuditLog(
                user_id=actor_id,
                action="UPDATE_USER",
                details_json={
                    "updated_user_id": user.id,
                    "email": user.email,
                    "role": role.name,
                    "password_changed": bool(password),
                    "google_calendar_changed": kalender_geaendert,
                },
            )
        )
        db.session.commit()
        return user, None, 200

    @staticmethod
    def get_all_users(actor: User) -> list[dict]:
        """Benutzerliste für die Verwaltung.

        * CEO/ADMIN sehen alle Benutzer, eine Teamleitung nur ihr eigenes Team.
        * ``joinedload`` lädt Rolle und Team im SELBEN SQL-Statement per JOIN.
          Ohne das würde für JEDEN Benutzer je eine Zusatzabfrage für ``u.role`` und
          ``u.team`` laufen (N+1-Problem: 100 Benutzer = 201 Queries statt 1).
        """
        query = User.query.options(joinedload(User.role), joinedload(User.team))
        if actor.role.name == RoleEnum.TEAM_LEADER.value:
            if actor.team_id is None:
                return []
            query = query.filter(User.team_id == actor.team_id)
        users = query.order_by(User.first_name).all()
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
                "google_calendar_id": u.google_calendar_id,
            }
            for u in users
        ]

    @staticmethod
    def toggle_status(user_id: int, actor_id: int) -> tuple[bool, str | None, int]:
        """Aktiviert bzw. deaktiviert ein Konto (Sperre wirkt sofort, siehe app/security.py)."""
        user = db.session.get(User, user_id)
        if not user:
            return False, "Benutzer nicht gefunden.", 404
        if user.id == actor_id:
            return False, "Selbst-Deaktivierung blockiert.", 400

        actor = db.session.get(User, actor_id)
        allowed, error = AuthorizationService.can_manage_user(actor, user)
        if not allowed:
            return False, error, 403

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
        db.session.commit()
        return True, None, 200

    @staticmethod
    def delete_user(target_user_id: int, actor_id: int) -> tuple[bool, str | None, int]:
        """Löscht einen Benutzer endgültig – nur, wenn er keine eigenen Termine angelegt hat.

        Zugewiesene Termine werden zur Neu-Zuweisung freigegeben, RSVPs gelöscht und
        eine eventuelle Teamleitung aufgehoben.
        """
        target_user = db.session.get(User, target_user_id)
        if not target_user:
            return False, "Benutzer nicht gefunden.", 404
        if target_user.id == actor_id:
            return False, "Du kannst dich nicht selbst löschen.", 400

        actor = db.session.get(User, actor_id)
        allowed, error = AuthorizationService.can_manage_user(actor, target_user)
        if not allowed:
            return False, error, 403

        if Event.query.filter_by(created_by_id=target_user_id).first():
            return (
                False,
                "Benutzer hat bereits eigene Termine erstellt. Bitte 'Deaktivieren' nutzen.",
                409,
            )

        # Massen-UPDATE/DELETE direkt in SQL (ohne jedes Objekt zu laden).
        Event.query.filter_by(assigned_to_id=target_user_id).update(
            {Event.assigned_to_id: None, Event.reallocation_required: True}
        )
        EventRSVP.query.filter_by(user_id=target_user_id).delete()
        Team.query.filter_by(team_leader_id=target_user_id).update({Team.team_leader_id: None})
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

    @staticmethod
    def import_csv(file: FileStorage, actor_id: int) -> tuple[dict, int]:
        """Massenimport aus CSV (Spalten: email, first_name, last_name, role).

        Ablauf:
            1. Datei als UTF-8 lesen (BOM von Excel wird toleriert).
            2. Vorab EINMAL alle existierenden E-Mails und alle Rollen laden
               (statt 2 Abfragen pro Zeile -> kein N+1).
            3. Pro gültiger Zeile: Benutzer mit zufälligem, unbekanntem Passwort anlegen.
            4. Nach dem Commit bekommt jeder neue Benutzer eine Einladung mit Link zum
               Festlegen seines Passworts (72 h gültig).

        Returns:
            ({"message": ..., "errors": [...]}, 200) oder ({"error": ...}, 400/403).
        """
        try:
            # utf-8-sig entfernt ein evtl. Byte-Order-Mark, das Excel voranstellt.
            content = file.stream.read().decode("utf-8-sig")
        except UnicodeDecodeError:
            return {"error": "Die Datei ist nicht UTF-8-kodiert."}, 400

        actor = db.session.get(User, actor_id)
        existing_emails = {email for (email,) in db.session.query(User.email).all()}
        roles_by_name = {role.name: role for role in Role.query.all()}

        reader = csv.DictReader(io.StringIO(content, newline=None))
        new_users: list[User] = []
        errors: list[str] = []
        # start=2: Zeile 1 ist die Kopfzeile -> Zeilennummern passen zu Excel.
        for row_num, row in enumerate(reader, start=2):
            email = (row.get("email") or "").strip().lower()
            first_name = (row.get("first_name") or "").strip()
            last_name = (row.get("last_name") or "").strip()
            role_name = (row.get("role") or RoleEnum.TRAINER.value).strip().upper()

            if not email:
                errors.append(f"Zeile {row_num}: E-Mail fehlt.")
                continue
            if not first_name or not last_name:
                errors.append(f"Zeile {row_num}: Vor- und Nachname sind erforderlich.")
                continue
            if email in existing_emails:
                errors.append(f"Zeile {row_num}: E-Mail {email} existiert bereits.")
                continue
            role = roles_by_name.get(role_name)
            if role is None:
                errors.append(f"Zeile {row_num}: Ungültige Rolle {role_name}.")
                continue
            allowed, auth_error = AuthorizationService.can_manage_user(actor, None, role_name)
            if not allowed:
                errors.append(f"Zeile {row_num}: {auth_error}")
                continue

            # Zufälliger Hash, den niemand kennt: Login erst nach "Passwort festlegen".
            user = User(
                email=email,
                first_name=first_name,
                last_name=last_name,
                role_id=role.id,
                password_hash=generate_password_hash(AuthService.random_password()),
                is_active=True,
            )
            db.session.add(user)
            new_users.append(user)
            existing_emails.add(email)  # Duplikate innerhalb derselben Datei abfangen

        db.session.flush()  # IDs für das Audit-Log
        for user in new_users:
            db.session.add(
                AuditLog(
                    user_id=actor_id,
                    action="CSV_IMPORT_USER",
                    details_json={"imported_user_id": user.id, "email": user.email},
                )
            )
            UserService._queue_invite(user)
        db.session.commit()
        return {"message": f"{len(new_users)} Benutzer importiert.", "errors": errors}, 200

    @staticmethod
    def _queue_invite(user: User) -> None:
        """Merkt die Einladungs-Mail (Link zum Passwort festlegen) für nach dem Commit vor."""
        token = AuthService.generate_password_token(user, purpose=PURPOSE_INVITE)
        url = AuthService.build_reset_url(token)
        html_body = render_template("email/account_invite.html", user=user, setup_url=url)
        text_body = (
            f"Hallo {user.first_name},\n\n"
            f"für dich wurde ein Konto im Bellmann Calendar angelegt. "
            f"Lege hier dein Passwort fest (Link 72 Stunden gültig):\n{url}\n"
        )
        EmailService.queue_email(
            user.email, "Dein Zugang zum Bellmann Calendar", text_body, html_body
        )
