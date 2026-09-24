"""
Tabelle ``users`` – alle Mitarbeiter mit Login.

Beziehungen:
    * n:1 ``roles``  über ``role_id``  (jede Person hat genau eine Rolle)
    * n:1 ``teams``  über ``team_id``  (optional; Teamleitungen verwalten ihr Team)
    * 1:1 ``teams.team_leader_id`` -> Rückreferenz ``led_team`` (definiert in team.py)
    * 1:n ``notifications`` (Rückreferenz ``notifications``, definiert in notification.py)

Wer benutzt das Model?
    AuthService (Login), UserService (Verwaltung), app/security.py (lädt den eingeloggten
    User bei jedem Request), EventService (Zuweisungen), TeamService.

Sicherheit: Es wird NIE das Passwort gespeichert, nur ein Hash (Werkzeug, PBKDF2/scrypt).
"""

from app import db
from app.utils.time import utc_now


class User(db.Model):
    """Ein Mitarbeiter/Benutzer des Kalendersystems."""

    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    # E-Mail ist der Login-Name -> eindeutig und indiziert (Login-Suche).
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    first_name = db.Column(db.String(50), nullable=False)
    last_name = db.Column(db.String(50), nullable=False)
    # Deaktivierte Benutzer können sich nicht anmelden; ihre Tokens werden sofort
    # ungültig, weil app/security.py::load_user is_active bei jedem Request prüft.
    is_active = db.Column(db.Boolean, default=True)
    # Optional: Kalender-ID (meist die Google-Mail) für Frei/Belegt-Abgleich.
    google_calendar_id = db.Column(db.String(255), nullable=True)
    # timezone=True -> PostgreSQL-Typ "timestamptz" (siehe app/utils/time.py).
    created_at = db.Column(db.DateTime(timezone=True), default=utc_now)

    # index=True: Fremdschlüssel werden in PostgreSQL NICHT automatisch indiziert.
    # Ohne Index wird z. B. "alle Benutzer mit Rolle X" zum Full-Table-Scan.
    role_id = db.Column(db.Integer, db.ForeignKey("roles.id"), nullable=False, index=True)
    role = db.relationship("Role", back_populates="users")

    team_id = db.Column(db.Integer, db.ForeignKey("teams.id"), nullable=True, index=True)
    team = db.relationship("Team", foreign_keys=[team_id], back_populates="members")

    @property
    def full_name(self) -> str:
        """Anzeigename "Vorname Nachname" (z. B. für Audit-Log und Dropdowns)."""
        return f"{self.first_name} {self.last_name}"

    def __repr__(self) -> str:
        return f"<User {self.email}>"
