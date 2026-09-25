"""
Tests für Anmeldung, Cookie-Sitzung, CSRF-Schutz und Passwort-Reset.

Geprüfte Sicherheitsanforderungen:
    * Tokens liegen in HttpOnly-Cookies, nicht im Response-Body (XSS kann nichts stehlen).
    * Schreibende Requests ohne X-CSRF-TOKEN werden abgewiesen.
    * Deaktivierung und Rechteentzug wirken SOFORT (User-Lookup pro Request).
    * Reset-Links sind einmalig, Passwort-Richtlinie greift.
"""

from app import db
from app.models import User
from app.services.auth_service import AuthService


def test_login_setzt_httponly_cookies_und_kein_token_im_body(client, make_user):
    user = make_user("TRAINER")
    response = client.post(
        "/api/v1/auth/login", json={"email": user.email, "password": "Sicheres-Passwort-123"}
    )
    assert response.status_code == 200
    body = response.get_json()
    assert "access_token" not in body
    assert body["user"]["role"] == "TRAINER"

    set_cookies = response.headers.getlist("Set-Cookie")
    access = next(c for c in set_cookies if c.startswith("access_token_cookie="))
    assert "HttpOnly" in access
    assert "SameSite=Strict" in access
    # Das CSRF-Cookie muss für JavaScript lesbar sein (kein HttpOnly).
    csrf_cookie = next(c for c in set_cookies if c.startswith("csrf_access_token="))
    assert "HttpOnly" not in csrf_cookie


def test_login_falsches_passwort_und_inaktiv_liefern_401(client, make_user):
    user = make_user("TRAINER")
    inactive = make_user("TRAINER", is_active=False)
    wrong = client.post(
        "/api/v1/auth/login", json={"email": user.email, "password": "falsch-falsch"}
    )
    assert wrong.status_code == 401
    blocked = client.post(
        "/api/v1/auth/login", json={"email": inactive.email, "password": "Sicheres-Passwort-123"}
    )
    assert blocked.status_code == 401


def test_me_liefert_daten_aus_der_datenbank(client, make_user, login):
    user = make_user("ADMIN")
    login(user)
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 200
    assert response.get_json()["email"] == user.email


def test_schreibender_request_ohne_csrf_header_wird_abgewiesen(client, make_user, login, csrf):
    user = make_user("CEO")
    login(user)
    payload = {"name": "Kunde A", "color_hex": "#112233"}
    assert client.post("/api/v1/customers", json=payload).status_code == 401
    assert client.post("/api/v1/customers", json=payload, headers=csrf()).status_code == 201


def test_refresh_und_logout(client, make_user, login, csrf):
    user = make_user("TRAINER")
    login(user)
    refreshed = client.post("/api/v1/auth/refresh", headers=csrf("csrf_refresh_token"))
    assert refreshed.status_code == 200

    client.post("/api/v1/auth/logout")
    assert client.get("/api/v1/auth/me").status_code == 401


def test_deaktivierung_wirkt_sofort(client, make_user, login):
    user = make_user("TRAINER")
    login(user)
    user.is_active = False
    db.session.commit()
    assert client.get("/api/v1/auth/me").status_code == 401


def test_rechteentzug_wirkt_sofort(client, make_user, login):
    admin = make_user("ADMIN")
    login(admin)
    assert client.get("/api/v1/events/audit").status_code == 200

    # Ohne neuen Login: Rolle in der DB auf TRAINER setzen.
    from app.models import Role

    admin.role_id = Role.query.filter_by(name="TRAINER").one().id
    db.session.commit()
    assert client.get("/api/v1/events/audit").status_code == 403


def test_passwort_reset_ist_einmalig(client, make_user):
    user = make_user("TRAINER")
    token = AuthService.generate_password_token(user)

    too_short = client.post(
        "/api/v1/auth/reset-password", json={"token": token, "password": "kurz"}
    )
    assert too_short.status_code == 400

    ok = client.post(
        "/api/v1/auth/reset-password", json={"token": token, "password": "Ganz-Neues-Passwort-1"}
    )
    assert ok.status_code == 200
    # Zweite Verwendung desselben Links scheitert (Passwort-Fingerabdruck hat sich geändert).
    reused = client.post(
        "/api/v1/auth/reset-password", json={"token": token, "password": "Noch-Ein-Passwort-2"}
    )
    assert reused.status_code == 400

    login = client.post(
        "/api/v1/auth/login", json={"email": user.email, "password": "Ganz-Neues-Passwort-1"}
    )
    assert login.status_code == 200


def test_forgot_password_antwortet_immer_gleich(client, make_user, sent_mails):
    user = make_user("TRAINER")
    known = client.post("/api/v1/auth/forgot-password", json={"email": user.email})
    unknown = client.post(
        "/api/v1/auth/forgot-password", json={"email": "gibt-es-nicht@example.com"}
    )
    assert known.status_code == unknown.status_code == 200
    assert known.get_json() == unknown.get_json()
    # Nur für die existierende Adresse wurde eine Mail verschickt – ohne Passwort im Betreff.
    assert sent_mails == [(user.email, "Passwort zurücksetzen")]
    assert db.session.get(User, user.id).password_hash == user.password_hash


# ====================================================================== Authelia (SSO)
def _sso_cookies(response) -> list[str]:
    return [c for c in response.headers.getlist("Set-Cookie") if c.startswith("access_token")]


def test_sso_aus_ignoriert_authelia_header(client, make_user):
    """Ohne AUTHELIA_SSO (lokal) darf der Header niemanden anmelden – er wäre fälschbar."""
    user = make_user("TRAINER")
    response = client.get("/login", headers={"Remote-Email": user.email})
    assert response.status_code == 200
    assert _sso_cookies(response) == []


def test_sso_meldet_passenden_mitarbeiter_ohne_passwort_an(app, client, make_user, monkeypatch):
    monkeypatch.setitem(app.config, "AUTHELIA_SSO", True)
    user = make_user("TRAINER", email="anna.muster@example.com")

    # Groß-/Kleinschreibung aus Authelia spielt keine Rolle.
    response = client.get("/login", headers={"Remote-Email": "Anna.Muster@Example.com"})
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/dashboard")
    assert _sso_cookies(response)

    me = client.get("/api/v1/auth/me", headers={"Remote-Email": user.email})
    assert me.status_code == 200
    assert me.get_json()["email"] == user.email


def test_sso_leitet_nur_auf_eigene_pfade_weiter(app, client, make_user, monkeypatch):
    monkeypatch.setitem(app.config, "AUTHELIA_SSO", True)
    user = make_user("TRAINER")
    headers = {"Remote-Email": user.email}

    ok = client.get("/login?next=/compare%3Fx%3D1", headers=headers)
    assert ok.headers["Location"].endswith("/compare?x=1")
    for bad in ("//evil.example", "https://evil.example", "/\\evil.example"):
        response = client.get("/login", query_string={"next": bad}, headers=headers)
        assert response.headers["Location"].endswith("/dashboard"), bad


def test_sso_unbekannt_inaktiv_oder_abgemeldet_zeigt_maske(app, client, make_user, monkeypatch):
    monkeypatch.setitem(app.config, "AUTHELIA_SSO", True)
    inactive = make_user("TRAINER", is_active=False)
    active = make_user("TRAINER")

    unknown = client.get("/login", headers={"Remote-Email": "fremd@example.com"})
    assert unknown.status_code == 200
    assert _sso_cookies(unknown) == []
    assert "kein aktives Mitarbeiterkonto" in unknown.get_data(as_text=True)

    blocked = client.get("/login", headers={"Remote-Email": inactive.email})
    assert blocked.status_code == 200
    assert _sso_cookies(blocked) == []

    # Nach "Abmelden" nicht sofort wieder anmelden, aber "Weiter als ..." anbieten.
    logged_out = client.get("/login?abgemeldet=1", headers={"Remote-Email": active.email})
    assert logged_out.status_code == 200
    assert _sso_cookies(logged_out) == []
    assert f"Weiter als {active.email}" in logged_out.get_data(as_text=True)


def test_sso_anderer_authelia_benutzer_verwirft_alte_sitzung(
    app, client, make_user, login, monkeypatch
):
    monkeypatch.setitem(app.config, "AUTHELIA_SSO", True)
    first = make_user("TRAINER")
    second = make_user("TRAINER")
    login(first)
    assert client.get("/api/v1/auth/me", headers={"Remote-Email": first.email}).status_code == 200
    # Im selben Browser meldet sich jemand anderes bei Authelia an.
    assert client.get("/api/v1/auth/me", headers={"Remote-Email": second.email}).status_code == 401


def test_logout_liefert_authelia_logout_url_nur_mit_sso(app, client, monkeypatch):
    monkeypatch.setitem(app.config, "AUTHELIA_LOGOUT_URL", "https://auth.example.com/logout")
    assert client.post("/api/v1/auth/logout").get_json()["redirect"] is None
    monkeypatch.setitem(app.config, "AUTHELIA_SSO", True)
    assert (
        client.post("/api/v1/auth/logout").get_json()["redirect"]
        == "https://auth.example.com/logout"
    )
