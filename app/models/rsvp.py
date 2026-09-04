from datetime import datetime, timezone
from enum import Enum
from app import db


class RSVPStatusEnum(str, Enum):
    """Erlaubte Rückmeldestatus für eine Termineinladung."""

    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    TENTATIVE = "TENTATIVE"


class EventRSVP(db.Model):
    """Speichert Rückmeldungen von Trainern inkl. Pflichtbegründung bei Ablehnung."""

    __tablename__ = "event_rsvps"

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(
        db.Integer, db.ForeignKey("events.id", ondelete="CASCADE"), nullable=False
    )
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)

    status = db.Column(db.String(20), default=RSVPStatusEnum.PENDING, nullable=False)
    rejection_reason = db.Column(db.Text, nullable=True)  # Pflichtfeld bei Ablehnung

    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=datetime.utcnow,
    )

    def __repr__(self):
        return f"<RSVP User:{self.user_id} Event:{self.event_id} Status:{self.status}>"
