from app import create_app, db
from app.models import Role, RoleEnum

app = create_app()


def seed_roles():
    """Initialisiert die Standard-Systemrollen."""
    with app.app_context():
        print("Erstelle Systemrollen...")

        role_permissions = {
            RoleEnum.CEO.value: ["*"],
            RoleEnum.ADMIN.value: [
                "users:manage",
                "events:manage",
                "skills:manage",
                "audit:read",
            ],
            RoleEnum.TEAM_LEADER.value: [
                "events:create",
                "events:read",
                "events:update",
                "rsvp:read",
            ],
            RoleEnum.TRAINER.value: ["events:read", "rsvp:update"],
        }

        for role_name, perms in role_permissions.items():
            existing_role = Role.query.filter_by(name=role_name).first()
            if not existing_role:
                new_role = Role(name=role_name, permissions_json=perms, is_custom=False)
                db.session.add(new_role)

        db.session.commit()
        print("Rollen erfolgreich initialisiert.")


if __name__ == "__main__":
    seed_roles()
