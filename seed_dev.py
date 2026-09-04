import os
from app import create_app, db
from app.models import User, Role, RoleEnum
from werkzeug.security import generate_password_hash

app = create_app()


def init_dev_user():
    with app.app_context():
        dev_email = os.getenv("DEV_USER_EMAIL", "***ENTFERNT***")
        dev_password = os.getenv("DEV_USER_PASSWORD")

        if not dev_password:
            print(
                "[!] ERROR: Definiert 'DEV_USER_PASSWORD' in deiner Datei .env bevor du fortfährst."
            )
            return

        ceo_role = Role.query.filter_by(name=RoleEnum.CEO.value).first()
        if not ceo_role:
            print(
                "[!] ERROR: Führe zuerst 'python seed.py' aus, um die Rollentabellen zu initialisieren."
            )
            return

        existing_user = User.query.filter_by(email=dev_email).first()
        if existing_user:
            print(f"[-] Der Benutzer {dev_email} ist bereits registriert.")
            return

        new_user = User(
            email=dev_email,
            password_hash=generate_password_hash(dev_password),
            first_name="Dev",
            last_name="Bellmann",
            role_id=ceo_role.id,
            is_active=True,
        )

        db.session.add(new_user)
        db.session.commit()
        print(f"[+] Benutzer für Entwicklung erfolgreich erstellt: {dev_email}")


if __name__ == "__main__":
    init_dev_user()
