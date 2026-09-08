"""HTTP-Endpunkte für Qualifikationen und Mitarbeiterzuordnungen."""

from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required
from app.decorators.auth import role_required
from app.services.skill_service import SkillService

skill_bp = Blueprint("skills", __name__, url_prefix="/api/v1/skills")


def _serialize_skill(skill: object) -> dict:
    """Wandelt einen Skill in die öffentliche API-Repräsentation um."""
    return {"id": skill.id, "name": skill.name, "description": skill.description}


def _serialize_user(user: object) -> dict:
    """Wandelt die für Skill-Filter erforderlichen Benutzerdaten um."""
    return {
        "id": user.id,
        "email": user.email,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "skills": [
            _serialize_skill(skill)
            for skill in sorted(user.skills, key=lambda item: item.name)
        ],
    }


@skill_bp.route("", methods=["GET"])
@jwt_required()
def list_skills():
    """Listet die verfügbaren Qualifikationen alphabetisch auf."""
    return (
        jsonify(
            {
                "skills": [
                    _serialize_skill(skill) for skill in SkillService.list_skills()
                ]
            }
        ),
        200,
    )


@skill_bp.route("", methods=["POST"])
@jwt_required()
@role_required("CEO", "ADMIN")
def create_skill():
    """Legt eine neue dynamische Qualifikation an."""
    data = request.get_json(silent=True) or {}
    skill, error, status_code = SkillService.create_skill(
        name=data.get("name"),
        actor_id=int(get_jwt_identity()),
        description=data.get("description"),
    )
    if error:
        return jsonify({"error": error}), status_code
    return (
        jsonify(
            {
                "message": "Qualifikation erfolgreich angelegt.",
                "skill": _serialize_skill(skill),
            }
        ),
        201,
    )


@skill_bp.route("/<int:skill_id>", methods=["PUT"])
@jwt_required()
@role_required("CEO", "ADMIN")
def update_skill(skill_id: int):
    """Aktualisiert eine Qualifikation."""
    data = request.get_json(silent=True) or {}
    skill, error, status_code = SkillService.update_skill(
        skill_id, data, int(get_jwt_identity())
    )
    if error:
        return jsonify({"error": error}), status_code
    return (
        jsonify(
            {"message": "Qualifikation aktualisiert.", "skill": _serialize_skill(skill)}
        ),
        200,
    )


@skill_bp.route("/<int:skill_id>", methods=["DELETE"])
@jwt_required()
@role_required("CEO", "ADMIN")
def delete_skill(skill_id: int):
    """Löscht eine Qualifikation."""
    success, error, status_code = SkillService.delete_skill(
        skill_id, int(get_jwt_identity())
    )
    if error:
        return jsonify({"error": error}), status_code
    return jsonify({"message": "Qualifikation gelöscht."}), 200


@skill_bp.route("/users/<int:user_id>", methods=["PUT"])
@jwt_required()
@role_required("CEO", "ADMIN")
def assign_skills(user_id: int):
    """Ersetzt die vollständige Skill-Zuordnung eines Mitarbeiters."""
    data = request.get_json(silent=True) or {}
    user, error, status_code = SkillService.assign_skills(
        user_id=user_id,
        skill_ids=data.get("skill_ids"),
        actor_id=int(get_jwt_identity()),
    )
    if error:
        return jsonify({"error": error}), status_code
    return (
        jsonify(
            {
                "message": "Qualifikationen erfolgreich zugeordnet.",
                "user": _serialize_user(user),
            }
        ),
        200,
    )


@skill_bp.route("/users", methods=["POST"])
@jwt_required()
@role_required("CEO", "ADMIN", "TEAM_LEADER")
def filter_users_by_skills():
    """Findet aktive Mitarbeiter, die alle angeforderten Skills besitzen."""
    data = request.get_json(silent=True) or {}
    users, error, status_code = SkillService.list_users_by_skills(data.get("skill_ids"))
    if error:
        return jsonify({"error": error}), status_code
    return jsonify({"users": [_serialize_user(user) for user in users]}), 200
