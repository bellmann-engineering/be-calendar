"""
Legt den ersten CEO-Zugang an (für Entwicklung und Erstinstallation).

Aufruf (nach ``python seed.py``):
    lokal:   python seed_dev.py
    Docker:  docker compose exec web python seed_dev.py   (macht setup.sh automatisch)

Liest aus der .env:
    DEV_USER_EMAIL     – Login-Adresse (Standard: dev@bellmann-engineering.com)
    DEV_USER_PASSWORD  – Pflicht; setup.sh erzeugt ein zufälliges Passwort.

Spricht mit: Tabellen ``roles`` und ``users``. Existiert die Adresse schon, passiert nichts.
"""

import os
import sys

from werkzeug.security import generate_password_hash

from app import create_app, db
from app.models import Role, RoleEnum, User

app = create_app()


def init_dev_user() -> int:
    """Erstellt den CEO-Benutzer. Rückgabe: Exit-Code (0 = OK, 1 = Fehler)."""
    with app.app_context():
        dev_email = os.getenv("DEV_USER_EMAIL", "dev@bellmann-engineering.com").strip().lower()
        dev_password = os.getenv("DEV_USER_PASSWORD")

        if not dev_password:
            print("[!] FEHLER: Bitte 'DEV_USER_PASSWORD' in der .env-Datei definieren.")
            return 1

        ceo_role = Role.query.filter_by(name=RoleEnum.CEO.value).first()
        if not ceo_role:
            print("[!] FEHLER: Zuerst 'python seed.py' ausführen (Rollen anlegen).")
            return 1

        if User.query.filter_by(email=dev_email).first():
            print(f"[-] Der Benutzer {dev_email} ist bereits registriert.")
            return 0

        db.session.add(
            User(
                email=dev_email,
                password_hash=generate_password_hash(dev_password),
                first_name="Dev",
                last_name="Bellmann",
                role_id=ceo_role.id,
                is_active=True,
            )
        )
        db.session.commit()
        print(f"[+] CEO-Benutzer erstellt: {dev_email}")
        return 0


if __name__ == "__main__":
    sys.exit(init_dev_user())
