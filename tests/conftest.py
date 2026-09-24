"""
Gemeinsame pytest-Fixtures für alle Tests.

Was passiert hier?
    1. Einmal pro Testlauf (Session):
       * App mit ``TestingConfig`` erzeugen.
       * Test-Datenbank komplett leeren und per ``flask db upgrade`` (Alembic) aufbauen.
         -> Jeder Testlauf prüft damit AUCH, dass alle Migrationen funktionieren.
    2. Vor jedem einzelnen Test:
       * Alle Tabellen leeren (TRUNCATE ... RESTART IDENTITY CASCADE) und die vier
         Rollen neu anlegen -> jeder Test startet mit identischem, sauberem Zustand.

Voraussetzung:
    Eine erreichbare PostgreSQL-Datenbank NUR für Tests, z. B.:
        export TEST_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/bellmann_test
    (SQLite reicht nicht: timestamptz, make_interval & Co. sind PostgreSQL-spezifisch.)
    ACHTUNG: Die Datenbank wird bei jedem Lauf vollständig gelöscht!

Hilfs-Fixtures:
    ``make_user``  – legt Benutzer mit Rolle (und optional Team) an.
    ``login``      – meldet einen Benutzer am Test-Client an (setzt die JWT-Cookies).
    ``csrf``       – liefert den X-CSRF-TOKEN-Header für schreibende Requests.
    ``sent_mails`` – fängt alle E-Mails ab, statt sie per SMTP zu verschicken.
"""

import os

import pytest
from sqlalchemy import text
from werkzeug.security import generate_password_hash

# Muss VOR dem Import von "app" gesetzt sein (config.py liest beim Import).
os.environ.setdefault("APP_ENV", "testing")

if not os.getenv("TEST_DATABASE_URL"):
    pytest.exit(
        "TEST_DATABASE_URL ist nicht gesetzt. Beispiel:\n"
        "  export TEST_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/bellmann_test",
        returncode=2,
    )

from flask_migrate import upgrade  # noqa: E402

from app import create_app, db  # noqa: E402
from app.config import TestingConfig  # noqa: E402
from app.models import Role, RoleEnum, Team, User  # noqa: E402

DEFAULT_PASSWORD = "Sicheres-Passwort-123"


@pytest.fixture(scope="session")
def app():
    """Eine App-Instanz für den gesamten Testlauf, Schema frisch per Alembic."""
    application = create_app(TestingConfig)
    with application.app_context():
        # Schema komplett zurücksetzen (auch alembic_version), dann alle Migrationen.
        db.session.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
        db.session.commit()
        upgrade(directory=os.path.join(os.path.dirname(__file__), "..", "migrations"))
        yield application
        db.session.remove()


@pytest.fixture(autouse=True)
def clean_db(app):
    """Vor jedem Test: alle Tabellen leeren und Standardrollen anlegen."""
    with app.app_context():
        tables = [t.name for t in db.metadata.sorted_tables]
        db.session.execute(text(f"TRUNCATE {', '.join(tables)} RESTART IDENTITY CASCADE"))
        for role in RoleEnum:
            db.session.add(Role(name=role.value, permissions_json=[], is_custom=False))
        db.session.commit()
        yield
        db.session.rollback()
        db.session.remove()


@pytest.fixture()
def client(app):
    """Flask-Test-Client (simuliert den Browser inkl. Cookies)."""
    return app.test_client()


@pytest.fixture()
def make_user(app):
    """Fabrik: ``make_user("ADMIN", team=team, email=...)`` -> gespeicherter User."""
    counter = {"n": 0}

    def _make(role: str = "TRAINER", team: Team | None = None, **kwargs) -> User:
        counter["n"] += 1
        role_obj = Role.query.filter_by(name=role).one()
        user = User(
            email=kwargs.pop("email", f"{role.lower()}{counter['n']}@example.com"),
            password_hash=generate_password_hash(kwargs.pop("password", DEFAULT_PASSWORD)),
            first_name=kwargs.pop("first_name", role.title()),
            last_name=kwargs.pop("last_name", str(counter["n"])),
            role_id=role_obj.id,
            team_id=team.id if team else None,
            is_active=kwargs.pop("is_active", True),
            **kwargs,
        )
        db.session.add(user)
        db.session.commit()
        return user

    return _make


@pytest.fixture()
def make_team(app):
    """Fabrik: ``make_team("Vertrieb", leader=user)`` -> gespeichertes Team."""

    def _make(name: str, leader: User | None = None) -> Team:
        team = Team(name=name, team_leader_id=leader.id if leader else None)
        db.session.add(team)
        db.session.commit()
        if leader:
            leader.team_id = team.id
            db.session.commit()
        return team

    return _make


@pytest.fixture()
def login(client):
    """Meldet ``user`` über die echte Login-Route an; Cookies bleiben im Client."""

    def _login(user: User, password: str = DEFAULT_PASSWORD):
        response = client.post(
            "/api/v1/auth/login", json={"email": user.email, "password": password}
        )
        assert response.status_code == 200, response.get_json()
        return response

    return _login


@pytest.fixture()
def csrf(client):
    """Header mit dem CSRF-Token aus dem (lesbaren) Cookie – wie app.js es macht."""

    def _headers(cookie_name: str = "csrf_access_token") -> dict:
        cookie = client.get_cookie(cookie_name)
        assert cookie is not None, f"Cookie {cookie_name} fehlt – eingeloggt?"
        return {"X-CSRF-TOKEN": cookie.value}

    return _headers


@pytest.fixture()
def sent_mails(monkeypatch):
    """Ersetzt den SMTP-Versand durch eine Liste: [(empfänger, betreff), ...]."""
    mails: list[tuple[str, str]] = []

    def fake_deliver(_settings, to_email, subject, _text, _html):
        mails.append((to_email, subject))
        return True

    monkeypatch.setattr("app.services.email_service._deliver", fake_deliver)
    return mails
