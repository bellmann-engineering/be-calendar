"""
Tabelle ``roles`` – die Systemrollen für das rollenbasierte Rechtekonzept (RBAC).

Hierarchie (von oben nach unten): CEO > ADMIN > TEAM_LEADER > TRAINER.
Die Hierarchie-Regeln selbst stehen in ``app/services/authorization_service.py``.

Beziehungen:
    * 1 Rolle -> n Benutzer (``User.role_id``)

Befüllt durch: ``seed.py`` (legt die vier Standardrollen an).
"""

from enum import StrEnum

from app import db


class RoleEnum(StrEnum):
    """Feste Rollennamen als Enum – verhindert Tippfehler wie "Admin" statt "ADMIN"."""

    CEO = "CEO"
    ADMIN = "ADMIN"
    TEAM_LEADER = "TEAM_LEADER"
    TRAINER = "TRAINER"


# Rang jeder Rolle: höhere Zahl = mehr Rechte. Genutzt vom AuthorizationService, um
# z. B. zu verhindern, dass ein ADMIN einen CEO bearbeitet oder sich selbst befördert.
ROLE_RANK: dict[str, int] = {
    RoleEnum.TRAINER.value: 1,
    RoleEnum.TEAM_LEADER.value: 2,
    RoleEnum.ADMIN.value: 3,
    RoleEnum.CEO.value: 4,
}


class Role(db.Model):
    """Eine Systemrolle mit optionalen, granularen Rechten im JSON-Format."""

    __tablename__ = "roles"

    id = db.Column(db.Integer, primary_key=True)
    # unique=True erzeugt in PostgreSQL automatisch einen Index -> schnelle Suche per Name.
    name = db.Column(db.String(50), unique=True, nullable=False)
    # z. B. ["events:create", "events:read"] – aktuell informativ, geprüft wird per Rolle.
    permissions_json = db.Column(db.JSON, nullable=False)
    is_custom = db.Column(db.Boolean, default=False)

    # Rückrichtung zu User.role (back_populates hält beide Seiten synchron).
    users = db.relationship("User", back_populates="role", lazy=True)

    def __repr__(self) -> str:
        return f"<Role {self.name}>"
