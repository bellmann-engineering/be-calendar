from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity, get_jwt
from app.services.auth_service import AuthService

auth_bp = Blueprint("auth", __name__, url_prefix="/api/v1/auth")


@auth_bp.route("/login", methods=["POST"])
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
