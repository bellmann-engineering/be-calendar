from datetime import datetime, timezone
from app import db


class AuditLog(db.Model):
    """Unveränderbare Historie aller Systemaktionen zur vollständigen Nachvollziehbarkeit."""

    __tablename__ = "audit_logs"

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(
        db.Integer, db.ForeignKey("events.id", ondelete="SET NULL"), nullable=True
    )
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    action = db.Column(db.String(100), nullable=False)
    # Korrigierter Timezone-Default
    timestamp = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )
    details_json = db.Column(db.JSON, nullable=True)

    def __repr__(self):
        return f"<AuditLog {self.action} by User:{self.user_id} at {self.timestamp}>"
