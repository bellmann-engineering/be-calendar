from flask import Blueprint, request, jsonify, render_template
from flask_jwt_extended import jwt_required, get_jwt_identity, get_jwt
from app.services.auth_service import AuthService
from app.services.user_service import UserService
from app.decorators.auth import role_required
from app import limiter
import secrets
from werkzeug.security import generate_password_hash
from app.services.email_service import EmailService
from app.models import User
from app import db

auth_bp = Blueprint("auth", __name__, url_prefix="/api/v1/auth")


@auth_bp.route("/login", methods=["POST"])
@limiter.limit("5 per minute")
def login():
    data = request.get_json() or {}
    email = data.get("email")
    password = data.get("password")

    if not email or not password:
        return jsonify({"error": "E-Mail und Passwort sind erforderlich."}), 400

    result = AuthService.authenticate_user(email, password)
    if not result:
        return (
            jsonify({"error": "Ungültige Anmeldedaten oder inaktiver Benutzer."}),
            401,
        )
    return jsonify(result), 200


@auth_bp.route("/me", methods=["GET"])
@jwt_required()
def me():
    current_user_id = get_jwt_identity()
    claims = get_jwt()
    return (
        jsonify(
            {
                "id": current_user_id,
                "role": claims.get("role"),
                "first_name": claims.get("first_name"),
                "last_name": claims.get("last_name"),
            }
        ),
        200,
    )


@auth_bp.route("/users", methods=["POST"])
@jwt_required()
@role_required("CEO", "ADMIN")
def create_user():
    data = request.get_json() or {}
    new_user, error, status_code = UserService.create_user(
        data, int(get_jwt_identity())
    )
    if error:
        return jsonify({"error": error}), status_code
    return (
        jsonify(
            {
                "message": f"Benutzer {new_user.email} wurde mit der Rolle {new_user.role.name} erfolgreich angelegt.",
                "user_id": new_user.id,
            }
        ),
        201,
    )


@auth_bp.route("/trainers", methods=["GET"])
@jwt_required()
def get_trainers():
    from app.models import Role, User

    trainers = (
        User.query.join(Role).filter(Role.name == "TRAINER", User.is_active).all()
    )
    return (
        jsonify(
            [{"id": t.id, "name": f"{t.first_name} {t.last_name}"} for t in trainers]
        ),
        200,
    )


@auth_bp.route("", methods=["GET"])
@jwt_required()
def get_all_users():
    return jsonify(UserService.get_all_users()), 200


@auth_bp.route("/users/<int:user_id>", methods=["PUT"])
@jwt_required()
@role_required("CEO", "ADMIN")
def update_user(user_id):
    data = request.get_json() or {}
    user, error, code = UserService.update_user(user_id, data, int(get_jwt_identity()))
    if error:
        return jsonify({"error": error}), code
    return jsonify({"message": "Benutzer aktualisiert."}), 200


@auth_bp.route("/<int:user_id>/status", methods=["PUT"])
@jwt_required()
@role_required("CEO", "ADMIN")
def toggle_user_status(user_id):
    success, msg, code = UserService.toggle_status(user_id, int(get_jwt_identity()))
    if not success:
        return jsonify({"error": msg}), code
    return jsonify({"message": "Status aktualisiert."}), 200


@auth_bp.route("/csv", methods=["POST"])
@jwt_required()
@role_required("CEO", "ADMIN")
def import_users_csv():
    if "file" not in request.files or request.files["file"].filename == "":
        return jsonify({"error": "Keine Datei hochgeladen"}), 400
    result, code = UserService.import_csv(
        request.files["file"], int(get_jwt_identity())
    )
    return jsonify(result), code


@auth_bp.route("/forgot-password", methods=["POST"])
def forgot_password():
    data = request.get_json() or {}
    email = data.get("email")
    if not email:
        return jsonify({"error": "E-Mail ist erforderlich."}), 400

    user = User.query.filter_by(email=email.strip().lower()).first()
    if not user or not user.is_active:
        # Generische Sicherheitsmeldung zur Vermeidung von Benutzer-Enumeration
        return (
            jsonify(
                {
                    "message": "Falls die E-Mail existiert, wurde ein neues Passwort versendet."
                }
            ),
            200,
        )

    new_pass = secrets.token_urlsafe(8)
    user.password_hash = generate_password_hash(new_pass)
    db.session.commit()

    html_body = render_template(
        "email/forgot_password.html",
        user=user,
        new_pass=new_pass,
        login_url="http://localhost:8080/login",
    )
    msg_text = f"Hallo {user.first_name}, dein neues Passwort lautet: {new_pass}"
    EmailService.send_email(
        user.email, "Passwort zurückgesetzt", msg_text, html_body=html_body
    )

    return (
        jsonify(
            {
                "message": "Falls die E-Mail existiert, wurde ein neues Passwort versendet."
            }
        ),
        200,
    )
