from enum import Enum
from app import db


class RoleEnum(str, Enum):
    """Enums für die Systemrollen zur Vermedung von Tippfehlern."""

    CEO = "CEO"
    ADMIN = "ADMIN"
    TEAM_LEADER = "TEAM_LEADER"
    TRAINER = "TRAINER"


class Role(db.Model):
    """Rollenmatrix für das Grandulare Rechtekonzept (RBAC)."""

    __tablename__ = "roles"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    permissions_json = db.Column(
        db.JSON, nullable=False
    )  # Granulare Rechte im JSON-Format
    is_custom = db.Column(db.Boolean, default=False)

    # Beziehung zu den Benutzern
    users = db.relationship("User", back_populates="role", lazy=True)

    def __repr__(self):
        return f"<Role {self.name}>"
