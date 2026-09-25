"""
Tabelle ``audit_logs`` – unveränderliche Historie aller wichtigen Systemaktionen.

Jeder Service schreibt hier beim Anlegen/Ändern/Löschen einen Eintrag (wer, was, wann,
Details als JSON). Angezeigt wird das Log unter /logs (nur CEO/ADMIN) über
``GET /api/v1/events/audit``.

Beziehungen:
    * n:1 ``events`` über ``event_id`` (ON DELETE SET NULL: Log bleibt erhalten)
    * n:1 ``users``  über ``user_id``  (ON DELETE SET NULL: Log bleibt erhalten)
"""

from app import db
from app.utils.time import utc_now


class AuditLog(db.Model):
    """Unveränderbare Historie aller Systemaktionen zur vollständigen Nachvollziehbarkeit."""

    __tablename__ = "audit_logs"

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(
        db.Integer,
        db.ForeignKey("events.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Maschinenlesbarer Aktionscode, z. B. CREATE_EVENT, UPDATE_EVENT, DELETE_USER.
    action = db.Column(db.String(100), nullable=False)
    # Indiziert, weil das Log immer "neueste zuerst" sortiert abgefragt wird.
    timestamp = db.Column(db.DateTime(timezone=True), default=utc_now, nullable=False, index=True)
    details_json = db.Column(db.JSON, nullable=True)

    def __repr__(self) -> str:
        return f"<AuditLog {self.action} by User:{self.user_id} at {self.timestamp}>"
