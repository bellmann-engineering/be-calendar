"""HTTP-Endpunkte für persönliche RSVP-Rückmeldungen."""

from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required

from app.services.rsvp_service import RSVPService

rsvp_bp = Blueprint("rsvps", __name__, url_prefix="/api/v1/events")


def _serialize_rsvp(rsvp: object) -> dict:
    """Wandelt ein RSVP-Modell in die öffentliche API-Repräsentation um."""
    return {
        "id": rsvp.id,
        "event_id": rsvp.event_id,
        "user_id": rsvp.user_id,
        "status": rsvp.status,
        "rejection_reason": rsvp.rejection_reason,
        "updated_at": rsvp.updated_at.isoformat() if rsvp.updated_at else None,
    }


@rsvp_bp.route("/<int:event_id>/rsvp", methods=["GET"])
@jwt_required()
def get_rsvp(event_id: int):
    """Liefert die eigene Rückmeldung zum angegebenen Termin."""
    rsvp, error, status_code = RSVPService.get_rsvp(event_id, int(get_jwt_identity()))
    if error:
        return jsonify({"error": error}), status_code
    return jsonify({"rsvp": _serialize_rsvp(rsvp)}), 200


@rsvp_bp.route("/<int:event_id>/rsvp", methods=["PUT"])
@jwt_required()
def update_rsvp(event_id: int):
    """Bestätigt, lehnt ab oder markiert die eigene Einladung als vorläufig."""
    data = request.get_json(silent=True) or {}
    rsvp, error, status_code = RSVPService.update_rsvp(
        event_id=event_id,
        user_id=int(get_jwt_identity()),
        status=data.get("status"),
        rejection_reason=data.get("rejection_reason", data.get("decline_reason")),
    )
    if error:
        return jsonify({"error": error}), status_code
    message = "RSVP-Rückmeldung erfolgreich aktualisiert."
    if rsvp.status == "DECLINED":
        message = "RSVP abgelehnt. Termin ist zur Neu-Zuweisung freigegeben."
    return jsonify({"message": message, "rsvp": _serialize_rsvp(rsvp)}), 200
