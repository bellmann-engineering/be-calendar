"""
Tabelle ``event_rsvps`` – Rückmeldungen ("Répondez s'il vous plaît") zu Terminen.

Ablauf:
    1. EventService legt beim Zuweisen eines Termins ein RSVP mit Status PENDING an.
    2. Der Trainer antwortet über ``PUT /api/v1/events/<id>/rsvp`` (RSVPService).
    3. Bei DECLINED ist eine Begründung Pflicht; der Termin wird zur Neu-Zuweisung
       freigegeben und die Teamleitung benachrichtigt.

Beziehungen:
    * n:1 ``events`` über ``event_id`` (ON DELETE CASCADE: RSVP stirbt mit dem Termin)
    * n:1 ``users``  über ``user_id``

Integrität: Pro (Termin, Benutzer) darf es genau EINE Rückmeldung geben ->
UniqueConstraint. Der dazugehörige Index deckt auch Abfragen "alle RSVPs zu Termin X" ab.
"""

from enum import StrEnum

from app import db
from app.utils.time import utc_now


class RSVPStatusEnum(StrEnum):
    """Erlaubte Rückmeldestatus für eine Termineinladung."""

    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    TENTATIVE = "TENTATIVE"


class EventRSVP(db.Model):
    """Speichert Rückmeldungen von Trainern inkl. Pflichtbegründung bei Ablehnung."""

    __tablename__ = "event_rsvps"
    __table_args__ = (db.UniqueConstraint("event_id", "user_id", name="uq_event_rsvps_event_user"),)

    id = db.Column(db.Integer, primary_key=True)
    # Kein eigener index=True nötig: Der Unique-Index (event_id, user_id) beginnt mit
    # event_id und wird von PostgreSQL auch für "WHERE event_id = ?" genutzt.
    event_id = db.Column(db.Integer, db.ForeignKey("events.id", ondelete="CASCADE"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)

    status = db.Column(db.String(20), default=RSVPStatusEnum.PENDING.value, nullable=False)
    rejection_reason = db.Column(db.Text, nullable=True)  # Pflichtfeld bei Ablehnung

    updated_at = db.Column(db.DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    def __repr__(self) -> str:
        return f"<RSVP User:{self.user_id} Event:{self.event_id} Status:{self.status}>"
