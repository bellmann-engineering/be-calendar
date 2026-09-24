from datetime import datetime, timezone
from app import db
from app.models.skill import user_skills


class User(db.Model):
    """Benutzerkonto-Entität."""

    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    first_name = db.Column(db.String(50), nullable=False)
    last_name = db.Column(db.String(50), nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    google_calendar_id = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    # Fremdschlüssel für die Rolle
    role_id = db.Column(db.Integer, db.ForeignKey("roles.id"), nullable=False)
    role = db.relationship("Role", back_populates="users")

    # Organisatorische Zuordnung für teambezogene Zugriffsregeln
    team_id = db.Column(
        db.Integer, db.ForeignKey("teams.id"), nullable=True, index=True
    )
    team = db.relationship("Team", foreign_keys=[team_id], back_populates="members")

    # Viele-zu-Viele-Beziehung zu Skills
    skills = db.relationship(
        "Skill", secondary=user_skills, backref=db.backref("users", lazy="dynamic")
    )

    def __repr__(self):
        return f"<User {self.email}>"
