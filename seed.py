"""
Initialdaten: legt die vier Standardrollen an (idempotent – mehrfach ausführbar).

Aufruf (nach ``flask db upgrade``):
    lokal:   python seed.py
    Docker:  docker compose exec web python seed.py   (macht setup.sh automatisch)

Spricht mit: Tabelle ``roles``. Bestehende Rollen werden nicht verändert.
"""

from app import create_app, db
from app.models import Role, RoleEnum

app = create_app()

# Granulare Rechte je Rolle (informativ; geprüft wird im Code über die Rolle selbst).
ROLE_PERMISSIONS: dict[str, list[str]] = {
    RoleEnum.CEO.value: ["*"],
    RoleEnum.ADMIN.value: ["users:manage", "events:manage", "audit:read"],
    RoleEnum.TEAM_LEADER.value: ["events:create", "events:read", "events:update", "rsvp:read"],
    RoleEnum.TRAINER.value: ["events:read", "rsvp:update"],
}


def seed_roles() -> None:
    """Initialisiert die Standard-Systemrollen, falls sie noch fehlen."""
    with app.app_context():
        print("Erstelle Systemrollen...")
        for role_name, perms in ROLE_PERMISSIONS.items():
            if not Role.query.filter_by(name=role_name).first():
                db.session.add(Role(name=role_name, permissions_json=perms, is_custom=False))
        db.session.commit()
        print("Rollen erfolgreich initialisiert.")


if __name__ == "__main__":
    seed_roles()
