"""
Tabelle ``notifications`` – In-App-Benachrichtigungen (Glocken-Symbol in der Navigation).

Erzeugt von: NotificationService.notify_user() (z. B. "Neuer Termin zugewiesen",
"Termin abgelehnt – Neu-Zuweisung erforderlich"). Parallel dazu wird – nach dem Commit –
eine E-Mail verschickt.

Gelesen über: ``GET /api/v1/notifications`` (nur die eigenen, neueste zuerst).

Beziehungen:
    * n:1 ``users`` über ``user_id`` (ON DELETE CASCADE)
"""

from app import db
from app.utils.time import utc_now


class Notification(db.Model):
    """Speichert In-App-Benachrichtigungen für Benutzer."""

    __tablename__ = "notifications"
    __table_args__ = (
        # Passt exakt zur Abfrage "WHERE user_id = ? ORDER BY created_at DESC".
        db.Index("ix_notifications_user_created", "user_id", "created_at"),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    title = db.Column(db.String(150), nullable=False)
    message = db.Column(db.Text, nullable=False)
    # Maschinenlesbarer Typ, z. B. 'REALLOCATION_REQUIRED', 'EVENT_ASSIGNED'.
    type = db.Column(db.String(50), nullable=False)

    is_read = db.Column(db.Boolean, default=False, nullable=False, index=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utc_now, nullable=False)

    user = db.relationship("User", backref=db.backref("notifications", lazy="select"))

    def __repr__(self) -> str:
        return f"<Notification {self.title} for User:{self.user_id} Read:{self.is_read}>"
