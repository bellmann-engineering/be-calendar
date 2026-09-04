"""HTTP-Endpunkte für In-App-Benachrichtigungen."""

from flask import Blueprint, jsonify
from flask_jwt_extended import get_jwt_identity, jwt_required
from app.services.notification_service import NotificationService

notification_bp = Blueprint(
    "notifications", __name__, url_prefix="/api/v1/notifications"
)


def _serialize_notification(notification) -> dict:
    return {
        "id": notification.id,
        "title": notification.title,
        "message": notification.message,
        "type": notification.type,
        "is_read": notification.is_read,
        "created_at": notification.created_at.isoformat(),
    }


@notification_bp.route("", methods=["GET"])
@jwt_required()
def get_notifications():
    """Liefert alle Benachrichtigungen des eingeloggten Benutzers."""
    user_id = int(get_jwt_identity())
    notifications = NotificationService.get_user_notifications(user_id)
    return (
        jsonify({"notifications": [_serialize_notification(n) for n in notifications]}),
        200,
    )


@notification_bp.route("/<int:notification_id>/read", methods=["PUT"])
@jwt_required()
def mark_as_read(notification_id: int):
    """Markiert eine Benachrichtigung als gelesen."""
    user_id = int(get_jwt_identity())
    success, error, status_code = NotificationService.mark_as_read(
        notification_id, user_id
    )
    if error:
        return jsonify({"error": error}), status_code
    return jsonify({"message": "Benachrichtigung als gelesen markiert."}), 200
