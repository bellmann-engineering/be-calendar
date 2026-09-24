"""
Plattform-Tests: Health-Check, Fehlerbehandlung, Konfiguration, Kunden-Validierung.
"""

import pytest

from app import create_app
from app.config import ProductionConfig, TestingConfig


def test_health_prueft_datenbank(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.get_json()["status"] == "healthy"


def test_unbekannte_api_route_liefert_json_404(client):
    response = client.get("/api/v1/gibt-es-nicht")
    assert response.status_code == 404
    assert response.get_json() == {"error": "Ressource nicht gefunden."}


def test_skills_route_ist_entfernt(client, make_user, login):
    login(make_user("CEO"))
    assert client.get("/api/v1/skills").status_code == 404


def test_unerwarteter_fehler_verraet_keine_details():
    """Ein Absturz in einer Route darf weder Stacktrace noch Fehlertext zeigen."""
    app = create_app(TestingConfig)
    # Werkzeug würde Exceptions im Testmodus sonst an pytest durchreichen.
    app.config["PROPAGATE_EXCEPTIONS"] = False

    @app.route("/api/v1/kaputt")
    def kaputt():
        raise RuntimeError("geheime interne Details: password=hunter2")

    response = app.test_client().get("/api/v1/kaputt")
    assert response.status_code == 500
    assert response.get_json() == {"error": "Interner Serverfehler."}
    assert b"hunter2" not in response.data


def test_produktion_startet_nicht_ohne_starke_secrets(monkeypatch):
    monkeypatch.setattr(ProductionConfig, "SQLALCHEMY_DATABASE_URI", "postgresql+psycopg://x/y")
    monkeypatch.setattr(ProductionConfig, "SECRET_KEY", None)
    monkeypatch.setattr(ProductionConfig, "JWT_SECRET_KEY", "zu-kurz")
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        ProductionConfig.validate()
    assert ProductionConfig.DEBUG is False


@pytest.mark.parametrize(
    "color, expected",
    [("#1A2B3C", 201), ("red", 400), ("#12345", 400), ('#000000"><script>', 400)],
)
def test_kundenfarbe_wird_validiert(client, make_user, login, csrf, color, expected):
    login(make_user("CEO"))
    response = client.post(
        "/api/v1/customers", json={"name": "Kunde", "color_hex": color}, headers=csrf()
    )
    assert response.status_code == expected
