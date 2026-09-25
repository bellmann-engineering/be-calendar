"""
HTTP-Endpunkte für Anmeldung, Sitzung und Benutzerverwaltung (/api/v1/auth/...).

Sitzungsmodell (Cookies statt localStorage):
    * ``POST /login``   -> setzt HttpOnly-Cookies ``access_token_cookie`` (30 min) und
                           ``refresh_token_cookie`` (8 h) plus die lesbaren CSRF-Cookies.
    * ``POST /refresh`` -> neues Access-Token, solange das Refresh-Token gültig ist.
                           Das Frontend (app.js::apiFetch) ruft das automatisch bei 401 auf.
    * ``POST /logout``  -> löscht alle Cookies.
    * Single Sign-on: Mit Authelia (AUTHELIA_SSO=1) setzt bereits ``GET /login``
      (calendar_routes.py) die Cookies – ganz ohne Passwort.
    JavaScript kann die Tokens nicht lesen -> ein XSS-Angriff kann sie nicht stehlen.

Wer ruft diese Endpunkte auf?
    ``app/static/js/app.js`` (Login, Logout, /me), ``members.html`` (Benutzerverwaltung),
    ``login.html`` (Passwort vergessen), ``reset_password.html``.

Wovon hängt die Datei ab?
    AuthService, UserService, AdminService, ``@role_required``, Flask-Limiter.

Rate-Limits: Zusätzlich zu Nginx (limit_req) begrenzt Flask-Limiter pro Client-IP.
"""

from flask import Blueprint, current_app, jsonify, request
from flask_jwt_extended import (
    create_access_token,
    current_user,
    jwt_required,
    set_access_cookies,
    unset_jwt_cookies,
)
from sqlalchemy import select

from app import db, limiter
from app.decorators.auth import role_required
from app.models import Role, RoleEnum, User
from app.security import set_session_cookies
from app.services.admin_service import AdminService
from app.services.auth_service import AuthService
from app.services.user_service import UserService

auth_bp = Blueprint("auth", __name__, url_prefix="/api/v1/auth")


def _serialize_me(user: User) -> dict:
    """Öffentliche Darstellung des eingeloggten Benutzers (ohne Passwort-Hash!)."""
    return {
        "id": user.id,
        "email": user.email,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "role": user.role.name,
        "team_id": user.team_id,
    }


# ====================================================================== Sitzung
@auth_bp.route("/login", methods=["POST"])
# Zweite Verteidigungslinie hinter Nginx (dort 20/min pro IP, prozessübergreifend).
@limiter.limit("30 per minute")
def login():
    """Prüft E-Mail/Passwort und setzt bei Erfolg die JWT-Cookies."""
    data = request.get_json(silent=True) or {}
    email = data.get("email")
    password = data.get("password")
    if not isinstance(email, str) or not isinstance(password, str) or not email or not password:
        return jsonify({"error": "E-Mail und Passwort sind erforderlich."}), 400

    user = AuthService.authenticate_user(email, password)
    if user is None:
        return jsonify({"error": "Ungültige Anmeldedaten oder inaktiver Benutzer."}), 401

    response = jsonify({"user": _serialize_me(user)})
    set_session_cookies(response, user)
    return response, 200


@auth_bp.route("/refresh", methods=["POST"])
@jwt_required(refresh=True)
def refresh():
    """Stellt ein neues Access-Token aus (verlangt Refresh-Cookie + CSRF-Header)."""
    response = jsonify({"message": "Sitzung verlängert."})
    set_access_cookies(response, create_access_token(identity=current_user))
    return response, 200


@auth_bp.route("/logout", methods=["POST"])
def logout():
    """Löscht alle Auth-Cookies. Bewusst ohne @jwt_required: Logout muss immer gehen.

    Mit Authelia liefert die Antwort ggf. ``redirect`` (AUTHELIA_LOGOUT_URL): Nur so endet
    auch die Authelia-Sitzung – sonst wäre man auf /login sofort wieder angemeldet.
    """
    config = current_app.config
    logout_url = config["AUTHELIA_LOGOUT_URL"] if config.get("AUTHELIA_SSO") else ""
    response = jsonify({"message": "Abgemeldet.", "redirect": logout_url or None})
    unset_jwt_cookies(response)
    return response, 200


@auth_bp.route("/me", methods=["GET"])
@jwt_required()
def me():
    """Daten des eingeloggten Benutzers (für Navigation, Rollen-Sichtbarkeit im Frontend)."""
    return jsonify(_serialize_me(current_user)), 200


# ====================================================================== Passwort
@auth_bp.route("/forgot-password", methods=["POST"])
@limiter.limit("5 per minute")
def forgot_password():
    """Verschickt einen Reset-Link. Antwort ist IMMER gleich (keine User-Enumeration)."""
    data = request.get_json(silent=True) or {}
    email = data.get("email")
    if not isinstance(email, str) or not email.strip():
        return jsonify({"error": "E-Mail ist erforderlich."}), 400
    AuthService.request_password_reset(email)
    return (
        jsonify(
            {"message": "Falls die E-Mail existiert, wurde ein Link zum Zurücksetzen versendet."}
        ),
        200,
    )


@auth_bp.route("/reset-password", methods=["POST"])
@limiter.limit("10 per minute")
def reset_password():
    """Setzt ein neues Passwort mit dem Token aus der E-Mail."""
    data = request.get_json(silent=True) or {}
    ok, error, code = AuthService.reset_password(data.get("token"), data.get("password"))
    if not ok:
        return jsonify({"error": error}), code
    return jsonify({"message": "Passwort gespeichert. Du kannst dich jetzt anmelden."}), 200


# ====================================================================== Benutzerverwaltung
@auth_bp.route("/users", methods=["POST"])
@jwt_required()
@role_required("CEO", "ADMIN")
def create_user():
    """Legt einen Benutzer an (Hierarchie-Prüfung im UserService)."""
    data = request.get_json(silent=True) or {}
    new_user, error, status_code = UserService.create_user(data, current_user.id)
    if error:
        return jsonify({"error": error}), status_code
    return (
        jsonify(
            {
                "message": (
                    f"Benutzer {new_user.email} wurde mit der Rolle "
                    f"{new_user.role.name} erfolgreich angelegt."
                ),
                "user_id": new_user.id,
            }
        ),
        201,
    )


@auth_bp.route("/trainers", methods=["GET"])
@jwt_required()
@role_required("CEO", "ADMIN", "TEAM_LEADER")
def get_trainers():
    """Aktive Trainer für die Zuweisungs-Dropdowns im Termin-Formular."""
    stmt = (
        select(User.id, User.first_name, User.last_name)
        .join(Role)
        .where(Role.name == RoleEnum.TRAINER.value, User.is_active.is_(True))
        .order_by(User.first_name)
    )
    rows = db.session.execute(stmt).all()
    return jsonify([{"id": r.id, "name": f"{r.first_name} {r.last_name}"} for r in rows]), 200


@auth_bp.route("", methods=["GET"])
@jwt_required()
@role_required("CEO", "ADMIN", "TEAM_LEADER")
def get_all_users():
    """Benutzerliste (Teamleitung sieht nur ihr Team). Früher für JEDEN Login sichtbar."""
    return jsonify(UserService.get_all_users(current_user)), 200


@auth_bp.route("/users/<int:user_id>", methods=["PUT"])
@jwt_required()
@role_required("CEO", "ADMIN")
def update_user(user_id: int):
    """Ändert einen Benutzer (Hierarchie-Prüfung im UserService)."""
    data = request.get_json(silent=True) or {}
    _user, error, code = UserService.update_user(user_id, data, current_user.id)
    if error:
        return jsonify({"error": error}), code
    return jsonify({"message": "Benutzer aktualisiert."}), 200


@auth_bp.route("/<int:user_id>/status", methods=["PUT"])
@jwt_required()
@role_required("CEO", "ADMIN")
def toggle_user_status(user_id: int):
    """Aktiviert/deaktiviert einen Benutzer."""
    success, msg, code = UserService.toggle_status(user_id, current_user.id)
    if not success:
        return jsonify({"error": msg}), code
    return jsonify({"message": "Status aktualisiert."}), 200


@auth_bp.route("/csv", methods=["POST"])
@jwt_required()
@role_required("CEO", "ADMIN")
@limiter.limit("10 per hour")
def import_users_csv():
    """CSV-Massenimport (multipart/form-data, Feld "file"). Größe begrenzt MAX_CONTENT_LENGTH."""
    if "file" not in request.files or request.files["file"].filename == "":
        return jsonify({"error": "Keine Datei hochgeladen"}), 400
    result, code = UserService.import_csv(request.files["file"], current_user.id)
    return jsonify(result), code


@auth_bp.route("/users/<int:user_id>/revoke-tl", methods=["PUT"])
@jwt_required()
@role_required("CEO", "ADMIN")
def revoke_tl_role(user_id: int):
    """Älterer Alias von /revoke-role."""
    result, code = AdminService.revoke_team_leader_role(user_id, current_user.id)
    return jsonify(result), code


@auth_bp.route("/users/<int:user_id>/revoke-role", methods=["PUT"])
@jwt_required()
@role_required("CEO", "ADMIN")
def revoke_elevated_role_route(user_id: int):
    """Stuft einen ADMIN/TEAM_LEADER auf TRAINER zurück."""
    result, code = AdminService.revoke_elevated_role(user_id, current_user.id)
    return jsonify(result), code


@auth_bp.route("/users/<int:user_id>", methods=["DELETE"])
@jwt_required()
@role_required("CEO", "ADMIN")
def delete_user_route(user_id: int):
    """Löscht einen Benutzer endgültig."""
    success, msg, code = UserService.delete_user(user_id, current_user.id)
    if not success:
        return jsonify({"error": msg}), code
    return jsonify({"message": "Benutzer erfolgreich und endgültig gelöscht."}), 200
