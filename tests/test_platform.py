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


# --- Frontend-Auslieferung (app/utils/assets.py, Templates) ------------------------------
SEITEN = ["/login", "/reset-password", "/dashboard", "/members", "/customers", "/logs", "/compare"]


@pytest.mark.parametrize("pfad", SEITEN)
def test_seiten_ohne_inline_javascript(client, pfad):
    """Die strenge CSP (script-src 'self') verlangt: kein Inline-JS, keine on*-Attribute."""
    import re

    response = client.get(pfad)
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert not re.search(r"<script(?![^>]*\bsrc=)[^>]*>", html), "Inline-<script> gefunden"
    assert not re.search(r"\son[a-z]+\s*=", html), "Inline-Event-Handler gefunden"
    assert "cdn.tailwindcss.com" not in html and "cdn.jsdelivr.net" not in html


def test_asset_url_mit_inhalts_hash_und_langem_cache(client):
    """Statische Dateien bekommen ?v=<hash> und dürfen dann 1 Jahr gecacht werden."""
    import re

    html = client.get("/login").get_data(as_text=True)
    treffer = re.search(r'src="(/static/js/app\.js\?v=[0-9a-f]{8})"', html)
    assert treffer, "app.js ohne Versions-Hash eingebunden"

    versioniert = client.get(treffer.group(1))
    assert versioniert.status_code == 200
    assert "immutable" in versioniert.headers["Cache-Control"]

    ohne_version = client.get("/static/js/app.js")
    assert ohne_version.headers["Cache-Control"] == "no-cache"


def test_asset_url_fehlende_datei_ohne_version(app):
    """Fehlt eine Datei (z. B. dist/ ohne Frontend-Build), gibt es trotzdem eine URL."""
    with app.test_request_context():
        url = app.jinja_env.globals["asset_url"]("gibt/es/nicht.css")
    assert url == "/static/gibt/es/nicht.css"
