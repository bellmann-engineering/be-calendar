"""HTTP-Endpunkte zur administrativen Verwaltung von Teams."""

from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required

from app.decorators.auth import role_required
from app.services.team_service import TeamService

team_bp = Blueprint("teams", __name__, url_prefix="/api/v1/teams")


def _serialize_user(user: object) -> dict:
    """Wandelt einen Benutzer in die für Teamantworten benötigte Repräsentation um."""
    return {
        "id": user.id,
        "email": user.email,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "team_id": user.team_id,
    }


@team_bp.route("", methods=["POST"])
@jwt_required()
@role_required("CEO", "ADMIN")
def create_team():
    """Legt ein Team an und kann eine Teamleitung zuordnen."""
    data = request.get_json(silent=True) or {}
    team, error, status_code = TeamService.create_team(
        name=data.get("name"),
        team_leader_id=data.get("team_leader_id"),
        actor_id=int(get_jwt_identity()),
    )
    if error:
        return jsonify({"error": error}), status_code
    return (
        jsonify(
            {
                "message": "Team erfolgreich angelegt.",
                "team": {
                    "id": team.id,
                    "name": team.name,
                    "team_leader_id": team.team_leader_id,
                },
            }
        ),
        201,
    )


@team_bp.route("/<int:team_id>/members/<int:user_id>", methods=["PUT"])
@jwt_required()
@role_required("CEO", "ADMIN")
def assign_member(team_id: int, user_id: int):
    """Ordnet einen Benutzer einem Team zu oder verschiebt ihn dorthin."""
    user, error, status_code = TeamService.assign_member(
        team_id, user_id, int(get_jwt_identity())
    )
    if error:
        return jsonify({"error": error}), status_code
    return (
        jsonify(
            {
                "message": "Teammitglied erfolgreich zugeordnet.",
                "user": _serialize_user(user),
            }
        ),
        200,
    )
