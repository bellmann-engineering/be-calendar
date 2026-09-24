"""
In-App-Benachrichtigungen (+ parallele E-Mail).

Was macht diese Datei?
    * ``notify_user()``            – legt eine Notification an und merkt eine E-Mail vor.
                                     Beides wird erst mit dem Commit des AUFRUFERS wirksam.
    * ``get_user_notifications()`` – Liste für die Glocke in der Navigation.
    * ``mark_as_read()``           – eine eigene Benachrichtigung als gelesen markieren.

Wer benutzt sie?
    EventService (Termin zugewiesen), RSVPService (Termin abgelehnt),
    Routen in ``app/routes/notification_routes.py``.

Womit spricht sie?
    Tabelle ``notifications`` und – indirekt – der SMTP-Server über EmailService.
"""

import logging

from app import db
from app.models import Notification, User
from app.services.email_service import EmailService

logger = logging.getLogger(__name__)


class NotificationService:
    """Service-Schicht für das In-App- und E-Mail-Benachrichtigungssystem."""

    @staticmethod
    def notify_user(
        user_id: int, title: str, message: str, notification_type: str
    ) -> Notification | None:
        """Erstellt eine Benachrichtigung und merkt eine E-Mail für nach dem Commit vor.

        Achtung: Diese Methode committet NICHT selbst. Sie ist Teil der Transaktion des
        Aufrufers (z. B. "Termin anlegen") – so entsteht nie eine Benachrichtigung zu
        einem Termin, der am Ende gar nicht gespeichert wurde.

        Returns:
            Die neue Notification oder None, wenn der Empfänger fehlt/inaktiv ist.
        """
        # db.session.get nutzt die Identity Map: Ist der User in diesem Request schon
        # geladen, kostet das keine weitere SQL-Abfrage.
        user = db.session.get(User, user_id)
        if not user or not user.is_active:
            return None

        notification = Notification(
            user_id=user.id, title=title, message=message, type=notification_type
        )
        db.session.add(notification)
        EmailService.queue_email(user.email, f"[Bellmann Calendar] {title}", message)
        return notification

    @staticmethod
    def get_user_notifications(user_id: int) -> list[Notification]:
        """Liefert alle Benachrichtigungen eines Benutzers, sortiert nach Erstelldatum."""
        return (
            Notification.query.filter_by(user_id=user_id)
            .order_by(Notification.created_at.desc())
            .all()
        )

    @staticmethod
    def mark_as_read(notification_id: int, user_id: int) -> tuple[bool, str | None, int]:
        """Markiert eine Benachrichtigung als gelesen – nur, wenn sie dem User gehört.

        Fremde IDs liefern bewusst 404 (nicht 403), um nicht zu verraten, dass die
        Benachrichtigung existiert (Schutz vor ID-Enumeration).
        """
        notification = db.session.get(Notification, notification_id)
        if not notification or notification.user_id != user_id:
            return False, "Benachrichtigung nicht gefunden.", 404

        notification.is_read = True
        db.session.commit()
        return True, None, 200
