from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from app.services.event_service import EventService
from app.decorators.auth import role_required

event_bp = Blueprint("events", __name__, url_prefix="/api/v1/events")


@event_bp.route("", methods=["POST"])
@jwt_required()
@role_required("CEO", "ADMIN", "TEAM_LEADER")
def create_event():
    """Erstellt einen neuen Termin mit detaillierter Fehlerbehandlung."""
    data = request.get_json() or {}
    required_fields = ["title", "start_time", "end_time"]

    if not all(field in data for field in required_fields):
        return (
            jsonify({"error": "Pflichtfelder fehlen: title, start_time, end_time"}),
            400,
        )

    creator_id = int(get_jwt_identity())
    event, error_message, status_code = EventService.create_event(data, creator_id)

    if error_message:
        return (
            jsonify(
                {"error": "Terminerstellung fehlgeschlagen", "message": error_message}
            ),
            status_code,
        )

    return (
        jsonify(
            {
                "message": "Termin erfolgreich erstellt.",
                "event": {
                    "id": event.id,
                    "title": event.title,
                    "start_time": event.start_time.isoformat(),
                    "end_time": event.end_time.isoformat(),
                    "assigned_to_id": event.assigned_to_id,
                    "buffer_before_mins": event.buffer_before_mins,
                    "buffer_after_mins": event.buffer_after_mins,
                    "required_skills": [
                        {"id": skill.id, "name": skill.name}
                        for skill in event.required_skills
                    ],
                    "qualification_warning": getattr(
                        event, "qualification_warning", None
                    ),
                },
            }
        ),
        201,
    )


@event_bp.route("", methods=["GET"])
@jwt_required()
def list_events():
    """Listet nur Termine auf, die für die Rolle sichtbar sind."""
    events, error_message, status_code = EventService.list_visible_events(
        int(get_jwt_identity())
    )
    if error_message:
        return jsonify({"error": error_message}), status_code
    result = [
        {
            "id": e.id,
            "title": e.title,
            "description": e.description,
            "start_time": e.start_time.isoformat(),
            "end_time": e.end_time.isoformat(),
            "assigned_to_id": e.assigned_to_id,
            "reallocation_required": e.reallocation_required,
            "required_skills": [
                {"id": skill.id, "name": skill.name} for skill in e.required_skills
            ],
            "buffer_before_mins": e.buffer_before_mins,
            "buffer_after_mins": e.buffer_after_mins,
        }
        for e in events
    ]
    return jsonify(result), 200


@event_bp.route("/<int:event_id>", methods=["PUT"])
@jwt_required()
@role_required("CEO", "ADMIN", "TEAM_LEADER")
def update_event(event_id):
    """Aktualisiert einen bestehenden Termin mit rollenbasierter Zugriffskontrolle."""
    data = request.get_json(silent=True) or {}
    event, error_message, status_code = EventService.update_event(
        event_id=event_id,
        data=data,
        user_id=int(get_jwt_identity()),
    )
    if error_message:
        return (
            jsonify(
                {
                    "error": "Terminaktualisierung fehlgeschlagen",
                    "message": error_message,
                }
            ),
            status_code,
        )
    return (
        jsonify(
            {
                "message": "Termin erfolgreich aktualisiert.",
                "event": {
                    "id": event.id,
                    "title": event.title,
                    "description": event.description,
                    "start_time": event.start_time.isoformat(),
                    "end_time": event.end_time.isoformat(),
                    "assigned_to_id": event.assigned_to_id,
                    "buffer_before_mins": event.buffer_before_mins,
                    "buffer_after_mins": event.buffer_after_mins,
                    "reallocation_required": event.reallocation_required,
                    "required_skills": [
                        {"id": skill.id, "name": skill.name}
                        for skill in event.required_skills
                    ],
                    "qualification_warning": getattr(
                        event, "qualification_warning", None
                    ),
                },
            }
        ),
        200,
    )


@event_bp.route("/<int:event_id>", methods=["DELETE"])
@jwt_required()
@role_required("CEO", "ADMIN", "TEAM_LEADER")
def delete_event(event_id):
    """Führt ein Soft-Delete für einen Termin durch."""
    user_id = int(get_jwt_identity())
    success, error_message, status_code = EventService.soft_delete_event(
        event_id, user_id
    )

    if not success:
        return jsonify({"error": error_message}), status_code

    return jsonify({"message": f"Termin {event_id} erfolgreich gelöscht."}), status_code
