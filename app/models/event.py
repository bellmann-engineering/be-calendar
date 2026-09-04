from datetime import datetime, timezone
from app import db
from app.models.skill import event_required_skills


class Event(db.Model):
    """Hauptmodell für Kalendereinträge inkl. Soft-Delete und Pufferzeiten."""

    __tablename__ = "events"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)

    recurrence_rule = db.Column(db.String(100), nullable=True)
    parent_event_id = db.Column(
        db.Integer, db.ForeignKey("events.id", ondelete="CASCADE"), nullable=True
    )

    exceptions = db.relationship(
        "Event", backref=db.backref("parent_event", remote_side=[id]), lazy="select"
    )

    start_time = db.Column(db.DateTime, nullable=False, index=True)
    end_time = db.Column(db.DateTime, nullable=False, index=True)

    buffer_before_mins = db.Column(db.Integer, default=0)
    buffer_after_mins = db.Column(db.Integer, default=0)

    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    assigned_to_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    created_by = db.relationship("User", foreign_keys=[created_by_id])
    assigned_to = db.relationship("User", foreign_keys=[assigned_to_id])
    required_skills = db.relationship(
        "Skill", secondary=event_required_skills, lazy="select"
    )

    is_deleted = db.Column(db.Boolean, default=False, nullable=False, index=True)
    deleted_at = db.Column(db.DateTime, nullable=True)
    reallocation_required = db.Column(
        db.Boolean, default=False, nullable=False, index=True
    )

    # Korrigierte Timezone-Defaults
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    def __repr__(self):
        return f"<Event {self.title} ({self.start_time} - {self.end_time})>"
