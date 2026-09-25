"""
Tabelle ``google_seen_events`` – welche Google-Termine ein Mitarbeiter schon kennt.

Wozu?
    Die Glocke soll melden, wenn im zugeordneten Google-Kalender eines Mitarbeiters ein
    NEUER Termin auftaucht (z. B. von der Planung direkt in Google eingetragen). Dafür
    merkt sich die App je Mitarbeiter die Schlüssel aller bereits gesehenen Termine;
    alles, was beim nächsten Abgleich neu dazukommt, wird zur Benachrichtigung.

Schlüssel:
    Die Google-Event-ID – bei Serienterminen die ID der Serie (``recurringEventId``),
    damit eine neue wöchentliche Serie EINE Meldung erzeugt und nicht zehn.

Wer benutzt sie?
    ``app/services/google_watch_service.py`` (Abgleich beim Abruf der Glocke).
"""

from app import db
from app.utils.time import utc_now


class GoogleSeenEvent(db.Model):
    """Ein bereits bekannter Google-Termin (bzw. eine Serie) eines Mitarbeiters."""

    __tablename__ = "google_seen_events"
    __table_args__ = (
        db.UniqueConstraint("user_id", "event_key", name="uq_google_seen_events_user_key"),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    event_key = db.Column(db.String(300), nullable=False)
    first_seen_at = db.Column(db.DateTime(timezone=True), default=utc_now, nullable=False)
