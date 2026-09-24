"""
Tabelle ``google_connections`` – die Verbindung der App mit EINEM Google-Konto (OAuth).

Idee (Wunsch von Kai Bellmann):
    Ein CEO/ADMIN meldet sich einmalig mit seinem Google-Konto an. Die App bekommt dabei
    ein Refresh-Token und kann damit dauerhaft alle Kalender lesen (und – mit
    Schreibrechten – Termine eintragen), die dieses Konto in Google Kalender sieht.
    Die Kalender werden anschließend einzelnen Mitarbeitern zugeordnet
    (``users.google_calendar_id``).

Es gibt höchstens EINEN Datensatz (neue Verbindung ersetzt die alte).

Sicherheit:
    ``refresh_token_enc`` ist mit Fernet verschlüsselt (app/utils/crypto.py) – der
    Klartext steht nie in der Datenbank. Ein Access-Token wird gar nicht gespeichert;
    es wird bei Bedarf aus dem Refresh-Token erzeugt und nur im Arbeitsspeicher gehalten.

Wer benutzt das Model?
    app/services/google_oauth_service.py (verbinden/trennen/Status) und
    app/services/calendar_service.py (Zugangsdaten für die Google-API).
"""

from app import db
from app.utils.time import utc_now


class GoogleConnection(db.Model):
    """Das verbundene Google-Konto inkl. verschlüsseltem Refresh-Token."""

    __tablename__ = "google_connections"

    id = db.Column(db.Integer, primary_key=True)
    # E-Mail des verbundenen Google-Kontos (nur zur Anzeige: "verbunden als …").
    account_email = db.Column(db.String(255), nullable=True)
    refresh_token_enc = db.Column(db.Text, nullable=False)
    # Von Google tatsächlich gewährte Berechtigungen (Leerzeichen-getrennt).
    scopes = db.Column(db.Text, nullable=False, default="")
    connected_by_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    connected_by = db.relationship("User", foreign_keys=[connected_by_id])
    connected_at = db.Column(db.DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = db.Column(
        db.DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    def __repr__(self) -> str:
        return f"<GoogleConnection {self.account_email}>"
