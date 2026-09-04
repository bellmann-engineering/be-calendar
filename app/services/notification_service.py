from typing import List, Optional, Tuple
from app import db
from app.models import Notification, User
from app.services.email_service import EmailService


class NotificationService:
    """Service-Schicht für das In-App- und E-Mail-Benachrichtigungssystem."""

    @staticmethod
    def notify_user(
        user_id: int, title: str, message: str, notification_type: str
    ) -> Optional[Notification]:
        """Erstellt eine In-App-Benachrichtigung und versucht gleichzeitig eine E-Mail zu senden."""
        user = db.session.get(User, user_id)
        if not user or not user.is_active:
            return None

        notification = Notification(
            user_id=user.id, title=title, message=message, type=notification_type
        )
        db.session.add(notification)

        try:
            EmailService.send_email(user.email, f"[Bellmann Calendar] {title}", message)
        except Exception:
            pass

        return notification

    @staticmethod
    def get_user_notifications(user_id: int) -> List[Notification]:
        """Liefert alle Benachrichtigungen eines Benutzers, sortiert nach Erstelldatum."""
        return (
            Notification.query.filter_by(user_id=user_id)
            .order_by(Notification.created_at.desc())
            .all()
        )

    @staticmethod
    def mark_as_read(
        notification_id: int, user_id: int
    ) -> Tuple[bool, Optional[str], int]:
        """Markiert eine Benachrichtigung als gelesen."""
        notification = db.session.get(Notification, notification_id)
        if not notification or notification.user_id != user_id:
            return False, "Benachrichtigung nicht gefunden.", 404

        try:
            notification.is_read = True
            db.session.commit()
            return True, None, 200
        except Exception as e:
            db.session.rollback()
            return (
                False,
                f"Fehler beim Aktualisieren der Benachrichtigung: {str(e)}",
                500,
            )
