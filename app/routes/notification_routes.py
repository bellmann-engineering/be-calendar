"""
HTTP-Endpunkte für In-App-Benachrichtigungen (/api/v1/notifications).

Wer ruft sie auf?
    ``app.js`` – Glocken-Symbol in der Navigation (laden, als gelesen markieren).

Wovon hängt die Datei ab?
    NotificationService, ``current_user`` (jeder sieht nur seine eigenen Einträge).
"""

from flask import Blueprint, jsonify
from flask_jwt_extended import current_user, jwt_required

from app.models import Notification
from app.services.notification_service import NotificationService
from app.utils.time import isoformat_utc

notification_bp = Blueprint("notifications", __name__, url_prefix="/api/v1/notifications")


def _serialize_notification(notification: Notification) -> dict:
    """JSON-Darstellung einer Benachrichtigung.

    Hinweis: ``title``/``message`` können vom Benutzer stammenden Text enthalten
    (z. B. Ablehnungsgrund). Das Frontend fügt sie deshalb nur per textContent ein.
    """
    return {
        "id": notification.id,
        "title": notification.title,
        "message": notification.message,
        "type": notification.type,
        "is_read": notification.is_read,
        "created_at": isoformat_utc(notification.created_at),
    }


@notification_bp.route("", methods=["GET"])
@jwt_required()
def get_notifications():
    """Liefert alle Benachrichtigungen des eingeloggten Benutzers."""
    notifications = NotificationService.get_user_notifications(current_user.id)
    return jsonify({"notifications": [_serialize_notification(n) for n in notifications]}), 200


@notification_bp.route("/<int:notification_id>/read", methods=["PUT"])
@jwt_required()
def mark_as_read(notification_id: int):
    """Markiert eine Benachrichtigung als gelesen."""
    _success, error, status_code = NotificationService.mark_as_read(
        notification_id, current_user.id
    )
    if error:
        return jsonify({"error": error}), status_code
    return jsonify({"message": "Benachrichtigung als gelesen markiert."}), 200
