from datetime import datetime, timezone
from app import db


class Notification(db.Model):
    """Speichert In-App-Benachrichtigungen für Benutzer."""

    __tablename__ = "notifications"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    title = db.Column(db.String(150), nullable=False)
    message = db.Column(db.Text, nullable=False)
    type = db.Column(
        db.String(50), nullable=False
    )  # z. B. 'REALLOCATION_REQUIRED', 'EVENT_ASSIGNED'

    is_read = db.Column(db.Boolean, default=False, nullable=False, index=True)
    created_at = db.Column(
        db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )

    user = db.relationship("User", backref=db.backref("notifications", lazy="select"))

    def __repr__(self):
        return (
            f"<Notification {self.title} for User:{self.user_id} Read:{self.is_read}>"
        )
