"""
Tabelle ``events`` – die Kalendertermine (Herzstück der Anwendung).

Beziehungen:
    * n:1 ``customers`` über ``customer_id``     -> ``event.customer`` (Farbe im Kalender)
    * n:1 ``users``     über ``created_by_id``   -> ``event.created_by`` (wer hat angelegt)
    * n:1 ``users``     über ``assigned_to_id``  -> ``event.assigned_to`` (wer führt durch)
    * n:1 ``events``    über ``parent_event_id`` -> ``event.parent_event`` (Serien/Ausnahmen)
    * 1:n ``event_rsvps`` und ``audit_logs`` (definiert in den jeweiligen Models)

Zeiten:
    ``start_time``/``end_time`` sind ``timestamptz`` (UTC). Die Pufferzeiten
    ``buffer_before_mins``/``buffer_after_mins`` verlängern den belegten Zeitraum für die
    Kollisionsprüfung (Anfahrt, Vorbereitung) – siehe EventService.check_conflict().

Löschen:
    Termine werden nur "soft" gelöscht (``is_deleted=True`` + ``deleted_at``), damit das
    Audit-Log nachvollziehbar bleibt.
"""

from app import db
from app.utils.time import utc_now


class Event(db.Model):
    """Ein Kalendertermin, optional einem Mitarbeiter und einem Kunden zugeordnet."""

    __tablename__ = "events"
    __table_args__ = (
        # Zusammengesetzter Index exakt für die häufigste/teuerste Abfrage:
        # check_conflict() sucht "aktive Termine von Mitarbeiter X im Zeitraum Y".
        # Reihenfolge = Filterreihenfolge (Gleichheit zuerst, Bereich zuletzt).
        db.Index("ix_events_assignee_active_start", "assigned_to_id", "is_deleted", "start_time"),
    )

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    meeting_link = db.Column(db.String(500), nullable=True)
    # ID des gespiegelten Termins in Google Calendar (zum späteren Löschen).
    google_event_id = db.Column(db.String(255), nullable=True)
    is_all_day = db.Column(db.Boolean, default=False, nullable=False)

    customer_id = db.Column(db.Integer, db.ForeignKey("customers.id"), nullable=True, index=True)
    customer = db.relationship("Customer", foreign_keys=[customer_id], backref="events")

    # Vorbereitet für Serientermine (RRULE nach RFC 5545), aktuell noch ungenutzt.
    recurrence_rule = db.Column(db.String(100), nullable=True)
    parent_event_id = db.Column(
        db.Integer,
        db.ForeignKey("events.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    exceptions = db.relationship(
        "Event", backref=db.backref("parent_event", remote_side=[id]), lazy="select"
    )

    start_time = db.Column(db.DateTime(timezone=True), nullable=False, index=True)
    end_time = db.Column(db.DateTime(timezone=True), nullable=False, index=True)
    buffer_before_mins = db.Column(db.Integer, default=0)
    buffer_after_mins = db.Column(db.Integer, default=0)

    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    assigned_to_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    created_by = db.relationship("User", foreign_keys=[created_by_id])
    assigned_to = db.relationship("User", foreign_keys=[assigned_to_id])

    is_deleted = db.Column(db.Boolean, default=False, nullable=False, index=True)
    deleted_at = db.Column(db.DateTime(timezone=True), nullable=True)
    # True, wenn der zugewiesene Trainer abgelehnt hat -> Teamleitung muss neu zuweisen.
    reallocation_required = db.Column(db.Boolean, default=False, nullable=False, index=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utc_now)
    updated_at = db.Column(db.DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    def __repr__(self) -> str:
        return f"<Event {self.title} ({self.start_time} - {self.end_time})>"
