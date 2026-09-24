"""
HTTP-Endpunkte für persönliche RSVP-Rückmeldungen (/api/v1/events/<id>/rsvp).

Wer ruft sie auf?
    ``app.js`` – Buttons "Bestätigen"/"Ablehnen" im Termin-Detail-Dialog (Trainer).

Wovon hängt die Datei ab?
    RSVPService, ``current_user`` (man kann nur die EIGENE Einladung beantworten).
"""

from flask import Blueprint, jsonify, request
from flask_jwt_extended import current_user, jwt_required

from app.models import EventRSVP
from app.services.rsvp_service import RSVPService
from app.utils.time import isoformat_utc

rsvp_bp = Blueprint("rsvps", __name__, url_prefix="/api/v1/events")


def _serialize_rsvp(rsvp: EventRSVP) -> dict:
    """Wandelt ein RSVP-Modell in die öffentliche API-Repräsentation um."""
    return {
        "id": rsvp.id,
        "event_id": rsvp.event_id,
        "user_id": rsvp.user_id,
        "status": rsvp.status,
        "rejection_reason": rsvp.rejection_reason,
        "updated_at": isoformat_utc(rsvp.updated_at),
    }


@rsvp_bp.route("/<int:event_id>/rsvp", methods=["GET"])
@jwt_required()
def get_rsvp(event_id: int):
    """Liefert die eigene Rückmeldung zum angegebenen Termin."""
    rsvp, error, status_code = RSVPService.get_rsvp(event_id, current_user.id)
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
        user_id=current_user.id,
        status=data.get("status"),
        # "decline_reason" wird als älterer Feldname weiterhin akzeptiert.
        rejection_reason=data.get("rejection_reason", data.get("decline_reason")),
    )
    if error:
        return jsonify({"error": error}), status_code
    message = "RSVP-Rückmeldung erfolgreich aktualisiert."
    if rsvp.status == "DECLINED":
        message = "RSVP abgelehnt. Termin ist zur Neu-Zuweisung freigegeben."
    return jsonify({"message": message, "rsvp": _serialize_rsvp(rsvp)}), 200
