from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from app.services.event_service import EventService
from app.decorators.auth import role_required
from app.models.rsvp import EventRSVP

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
                    "start_time": (
                        event.start_time.isoformat() if event.start_time else None
                    ),
                    "end_time": event.end_time.isoformat() if event.end_time else None,
                    "assigned_to_id": event.assigned_to_id,
                    "meeting_link": getattr(event, "meeting_link", None),
                    "buffer_before_mins": event.buffer_before_mins,
                    "buffer_after_mins": event.buffer_after_mins,
                    "is_all_day": getattr(event, "is_all_day", False),
                    "customer_id": getattr(event, "customer_id", None),
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

    result = []
    for e in events:
        color_val = "#2B6CB0"
        try:
            if getattr(e, "customer", None) and hasattr(e.customer, "color_hex"):
                color_val = e.customer.color_hex or "#2B6CB0"
        except Exception:
            pass

        rejection_reason = None
        if getattr(e, "reallocation_required", False):
            rsvp = (
                EventRSVP.query.filter_by(event_id=e.id, status="DECLINED")
                .order_by(EventRSVP.updated_at.desc())
                .first()
            )
            if rsvp:
                rejection_reason = rsvp.rejection_reason

        result.append(
            {
                "id": e.id,
                "is_mandatory": getattr(e, "is_mandatory", False),
                "rejection_reason": rejection_reason,
                "title": e.title,
                "description": e.description,
                "start_time": e.start_time.isoformat() if e.start_time else None,
                "end_time": e.end_time.isoformat() if e.end_time else None,
                "assigned_to_id": e.assigned_to_id,
                "meeting_link": getattr(e, "meeting_link", None),
                "reallocation_required": getattr(e, "reallocation_required", False),
                "required_skills": [
                    {"id": skill.id, "name": skill.name}
                    for skill in (e.required_skills or [])
                ],
                "buffer_before_mins": getattr(e, "buffer_before_mins", 15),
                "buffer_after_mins": getattr(e, "buffer_after_mins", 15),
                "is_all_day": getattr(e, "is_all_day", False),
                "customer_id": getattr(e, "customer_id", None),
                "color": color_val,
            }
        )
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
                    "start_time": (
                        event.start_time.isoformat() if event.start_time else None
                    ),
                    "end_time": event.end_time.isoformat() if event.end_time else None,
                    "assigned_to_id": event.assigned_to_id,
                    "meeting_link": getattr(event, "meeting_link", None),
                    "buffer_before_mins": event.buffer_before_mins,
                    "buffer_after_mins": event.buffer_after_mins,
                    "is_all_day": getattr(event, "is_all_day", False),
                    "customer_id": getattr(event, "customer_id", None),
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


@event_bp.route("/audit", methods=["GET"])
@jwt_required()
@role_required("CEO", "ADMIN")
def get_audit():
    """Liefert die letzten 1000 Audit Logs inkl. Rollen an das Frontend."""
    from app.models import AuditLog, User, Role
    from app import db

    logs = (
        db.session.query(AuditLog, User, Role)
        .outerjoin(User, AuditLog.user_id == User.id)
        .outerjoin(Role, User.role_id == Role.id)
        .order_by(AuditLog.timestamp.desc())
        .limit(1000)
        .all()
    )
    result = []
    for log, user, role in logs:
        result.append(
            {
                "timestamp": log.timestamp.isoformat(),
                "user_name": (
                    f"{user.first_name} {user.last_name}" if user else "System"
                ),
                "role": role.name if role else "SYSTEM",
                "action": log.action,
                "details": str(log.details_json) if log.details_json else "-",
            }
        )
    return jsonify(result), 200
