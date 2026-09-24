"""
Tests für die Google-Kalender-Anbindung (OAuth-Verbindung, Zuordnung, Synchronisierung).

Google selbst wird NIE aufgerufen: Die Fixture ``fake_google`` ersetzt die Methoden von
GoogleCalendarService durch eine Attrappe, die jeden Aufruf protokolliert. So lässt sich
genau prüfen, WAS die App in Google tun würde (anlegen, ändern, umziehen, löschen).
"""

import pytest

from app import db
from app.models import AuditLog, Event, GoogleConnection, User
from app.services import calendar_service
from app.utils.crypto import decrypt_text, encrypt_text


class FakeGoogle:
    """Protokolliert alle Google-Aufrufe und liefert vorhersehbare Antworten.

    Die Methoden werden als bereits gebundene Methoden in die Klasse
    GoogleCalendarService eingesetzt – deshalb haben sie KEINEN zusätzlichen Parameter
    für die GoogleCalendarService-Instanz.
    """

    def __init__(self) -> None:
        self.aufrufe: list[tuple] = []
        self.busy: dict[str, list] = {}
        self._zaehler = 0

    def insert(self, calendar_id, title, *_args, **_kw):
        self._zaehler += 1
        self.aufrufe.append(("insert", calendar_id, title))
        return f"g{self._zaehler}"

    def update(self, calendar_id, event_id, title, *_args, **_kw):
        self.aufrufe.append(("update", calendar_id, event_id, title))
        return True

    def delete(self, calendar_id, event_id):
        self.aufrufe.append(("delete", calendar_id, event_id))
        return True

    def busy_map(self, ids, *_args):
        return {i: self.busy.get(i, []) for i in ids}


@pytest.fixture()
def fake_google(monkeypatch):
    fake = FakeGoogle()
    cls = calendar_service.GoogleCalendarService
    monkeypatch.setattr(cls, "_get_thread_service", lambda self: object())
    monkeypatch.setattr(cls, "insert_event", fake.insert)
    monkeypatch.setattr(cls, "update_event", fake.update)
    monkeypatch.setattr(cls, "delete_event", fake.delete)
    monkeypatch.setattr(cls, "get_busy_map", fake.busy_map)
    monkeypatch.setattr(
        cls,
        "list_calendars",
        lambda self: [
            {
                "id": "anna@gmail.com",
                "summary": "Anna",
                "access_role": "writer",
                "primary": False,
                "color": None,
            }
        ],
    )
    monkeypatch.setattr(
        cls,
        "check_calendar",
        lambda self, cid: (True, "writer", "Verbindung in Ordnung – Rechte: Bearbeiten."),
    )
    return fake


def _termin(
    assignee_id, start="2026-11-02T09:00:00+01:00", ende="2026-11-02T10:00:00+01:00", **extra
):
    return {
        "title": "Schulung",
        "start_time": start,
        "end_time": ende,
        "assigned_to_id": assignee_id,
        **extra,
    }


def _verbindung_anlegen(user):
    db.session.add(
        GoogleConnection(
            account_email="kai@gmail.com",
            refresh_token_enc=encrypt_text("rt-123"),
            scopes="x",
            connected_by_id=user.id,
        )
    )
    db.session.commit()


# ------------------------------------------------------------------ Verschlüsselung
def test_token_verschluesselung_rundreise(app):
    geheim = encrypt_text("mein-refresh-token")
    assert "mein-refresh-token" not in geheim
    assert decrypt_text(geheim) == "mein-refresh-token"
    assert decrypt_text("manipuliert") is None


# ------------------------------------------------------------------ Status & Rechte
def test_status_nur_fuer_ceo_und_admin(client, make_user, login):
    login(make_user("TRAINER"))
    assert client.get("/api/v1/google/status").status_code == 403


def test_status_zeigt_verbindung_ohne_token(client, make_user, login):
    ceo = make_user("CEO")
    _verbindung_anlegen(ceo)
    login(ceo)
    daten = client.get("/api/v1/google/status").get_json()
    assert daten["configured"] is True and daten["connected"] is True
    assert daten["account_email"] == "kai@gmail.com"
    assert "rt-123" not in str(daten) and "refresh" not in str(daten)


# ------------------------------------------------------------------ OAuth-Ablauf
def test_oauth_start_liefert_google_url_mit_pkce(client, make_user, login, csrf):
    login(make_user("CEO"))
    antwort = client.post("/api/v1/google/oauth/start", headers=csrf())
    assert antwort.status_code == 200
    url = antwort.get_json()["authorization_url"]
    assert url.startswith("https://accounts.google.com/")
    assert "code_challenge=" in url and "access_type=offline" in url and "state=" in url


def test_oauth_callback_mit_falschem_state_wird_abgelehnt(client, make_user, login, csrf):
    login(make_user("CEO"))
    client.post("/api/v1/google/oauth/start", headers=csrf())
    antwort = client.get("/api/v1/google/oauth/callback?code=abc&state=gefaelscht")
    assert antwort.status_code == 302
    assert "google=fehler" in antwort.headers["Location"]
    assert GoogleConnection.query.count() == 0


def test_oauth_callback_speichert_token_verschluesselt(client, make_user, login, csrf, monkeypatch):
    ceo = make_user("CEO")
    login(ceo)
    url = client.post("/api/v1/google/oauth/start", headers=csrf()).get_json()["authorization_url"]
    state = url.split("state=")[1].split("&")[0]

    class FakeCreds:
        refresh_token = "echtes-refresh-token"
        token = "access"
        granted_scopes = calendar_service.OAUTH_SCOPES
        scopes = calendar_service.OAUTH_SCOPES

    from google_auth_oauthlib.flow import Flow

    monkeypatch.setattr(Flow, "fetch_token", lambda self, **kw: None)
    monkeypatch.setattr(Flow, "credentials", property(lambda self: FakeCreds()))
    monkeypatch.setattr(
        "app.services.google_oauth_service.GoogleOAuthService._kontoadresse",
        staticmethod(lambda t: "kai@gmail.com"),
    )
    antwort = client.get(f"/api/v1/google/oauth/callback?code=abc&state={state}")
    assert antwort.status_code == 302 and "google=verbunden" in antwort.headers["Location"]

    db.session.expire_all()
    verbindung = GoogleConnection.query.one()
    assert verbindung.account_email == "kai@gmail.com"
    assert "echtes-refresh-token" not in verbindung.refresh_token_enc  # nie im Klartext
    assert decrypt_text(verbindung.refresh_token_enc) == "echtes-refresh-token"
    assert AuditLog.query.filter_by(action="GOOGLE_CONNECTED").count() == 1


def test_trennen_widerruft_und_loescht(client, make_user, login, csrf, monkeypatch):
    ceo = make_user("CEO")
    _verbindung_anlegen(ceo)
    widerrufen = []
    monkeypatch.setattr(
        "app.services.google_oauth_service.requests.post",
        lambda url, params, timeout: widerrufen.append(params["token"]),
    )
    login(ceo)
    assert client.post("/api/v1/google/disconnect", headers=csrf()).status_code == 200
    assert widerrufen == ["rt-123"]
    assert GoogleConnection.query.count() == 0


# ------------------------------------------------------------------ Kalender & Zuordnung
def test_kalenderliste_braucht_verbindung(client, make_user, login, fake_google):
    ceo = make_user("CEO")
    login(ceo)
    assert client.get("/api/v1/google/calendars").status_code == 409
    _verbindung_anlegen(ceo)
    daten = client.get("/api/v1/google/calendars").get_json()
    assert daten["calendars"][0]["id"] == "anna@gmail.com"


def test_kalender_zuordnen_und_pruefen(client, make_user, login, csrf, fake_google):
    ceo = make_user("CEO")
    trainer = make_user("TRAINER")
    login(ceo)
    antwort = client.put(
        f"/api/v1/auth/users/{trainer.id}",
        json={"google_calendar_id": " anna@gmail.com "},
        headers=csrf(),
    )
    assert antwort.status_code == 200
    db.session.expire_all()
    assert db.session.get(User, trainer.id).google_calendar_id == "anna@gmail.com"
    liste = client.get("/api/v1/auth").get_json()
    assert any(u["google_calendar_id"] == "anna@gmail.com" for u in liste)

    pruefung = client.post(
        "/api/v1/google/calendars/check", json={"calendar_id": "anna@gmail.com"}, headers=csrf()
    )
    assert pruefung.get_json()["ok"] is True

    entfernen = client.put(
        f"/api/v1/auth/users/{trainer.id}", json={"google_calendar_id": ""}, headers=csrf()
    )
    assert entfernen.status_code == 200
    db.session.expire_all()
    assert db.session.get(User, trainer.id).google_calendar_id is None


def test_ungueltige_kalender_id_wird_abgelehnt(client, make_user, login, csrf):
    ceo = make_user("CEO")
    trainer = make_user("TRAINER")
    login(ceo)
    antwort = client.put(
        f"/api/v1/auth/users/{trainer.id}",
        json={"google_calendar_id": "mit leerzeichen"},
        headers=csrf(),
    )
    assert antwort.status_code == 400


# ------------------------------------------------------------------ Synchronisierung
def test_sync_anlegen_aendern_umziehen_loeschen(client, make_user, login, csrf, fake_google):
    ceo = make_user("CEO")
    anna = make_user("TRAINER", google_calendar_id="anna@gmail.com")
    ben = make_user("TRAINER", google_calendar_id="ben@gmail.com")
    login(ceo)

    # 1. Anlegen -> Kopie in Annas Kalender
    event_id = client.post("/api/v1/events", json=_termin(anna.id), headers=csrf()).get_json()[
        "event"
    ]["id"]
    assert fake_google.aufrufe == [("insert", "anna@gmail.com", "Schulung")]
    db.session.expire_all()
    event = db.session.get(Event, event_id)
    assert (event.google_event_id, event.google_sync_calendar_id) == ("g1", "anna@gmail.com")

    # 2. Verschieben -> Kopie wird geändert
    client.put(
        f"/api/v1/events/{event_id}", json={"end_time": "2026-11-02T10:30:00+01:00"}, headers=csrf()
    )
    assert fake_google.aufrufe[-1] == ("update", "anna@gmail.com", "g1", "Schulung")

    # 3. Neu zuweisen -> bei Anna löschen, bei Ben anlegen
    client.put(f"/api/v1/events/{event_id}", json={"assigned_to_id": ben.id}, headers=csrf())
    assert fake_google.aufrufe[-2:] == [
        ("delete", "anna@gmail.com", "g1"),
        ("insert", "ben@gmail.com", "Schulung"),
    ]

    # 4. Löschen -> bei Ben entfernen, IDs zurückgesetzt
    client.delete(f"/api/v1/events/{event_id}", headers=csrf())
    assert fake_google.aufrufe[-1] == ("delete", "ben@gmail.com", "g2")
    db.session.expire_all()
    event = db.session.get(Event, event_id)
    assert event.google_event_id is None and event.google_sync_calendar_id is None


def test_sync_bei_absage_entfernt_kopie(client, make_user, login, csrf, fake_google):
    ceo = make_user("CEO")
    anna = make_user("TRAINER", google_calendar_id="anna@gmail.com")
    login(ceo)
    event_id = client.post("/api/v1/events", json=_termin(anna.id), headers=csrf()).get_json()[
        "event"
    ]["id"]
    client.post("/api/v1/auth/logout")

    login(anna)
    client.put(
        f"/api/v1/events/{event_id}/rsvp",
        json={"status": "DECLINED", "rejection_reason": "krank"},
        headers=csrf(),
    )
    assert fake_google.aufrufe[-1] == ("delete", "anna@gmail.com", "g1")


def test_ohne_kalender_kein_google_aufruf(client, make_user, login, csrf, fake_google):
    ceo = make_user("CEO")
    trainer = make_user("TRAINER")
    login(ceo)
    client.post("/api/v1/events", json=_termin(trainer.id), headers=csrf())
    assert fake_google.aufrufe == []


# ------------------------------------------------------------------ Belegt-Anzeige
def test_busy_respektiert_sichtbarkeit(client, make_user, login, fake_google):
    anna = make_user("TRAINER", google_calendar_id="anna@gmail.com")
    ben = make_user("TRAINER", google_calendar_id="ben@gmail.com")
    fake_google.busy = {
        "anna@gmail.com": [{"start": "2026-11-02T08:00:00Z", "end": "2026-11-02T09:00:00Z"}],
        "ben@gmail.com": [{"start": "2026-11-02T10:00:00Z", "end": "2026-11-02T11:00:00Z"}],
    }
    login(anna)
    daten = client.get(
        "/api/v1/google/busy",
        query_string={
            "start": "2026-11-02T00:00:00Z",
            "end": "2026-11-03T00:00:00Z",
            "user_ids": f"{anna.id},{ben.id}",
        },
    ).get_json()
    # Ein Trainer sieht nur seine eigenen Belegt-Zeiten, nicht die von Ben.
    assert list(daten["busy"].keys()) == [str(anna.id)]


def test_busy_fuer_ceo_und_zeitraum_grenze(client, make_user, login, fake_google):
    ceo = make_user("CEO")
    anna = make_user("TRAINER", google_calendar_id="anna@gmail.com")
    fake_google.busy = {
        "anna@gmail.com": [{"start": "2026-11-02T08:00:00Z", "end": "2026-11-02T09:00:00Z"}]
    }
    login(ceo)
    daten = client.get(
        "/api/v1/google/busy",
        query_string={
            "start": "2026-11-02T00:00:00Z",
            "end": "2026-11-03T00:00:00Z",
            "user_ids": str(anna.id),
        },
    ).get_json()
    assert daten["connected"] is True and len(daten["busy"][str(anna.id)]) == 1
    zu_lang = client.get(
        "/api/v1/google/busy",
        query_string={"start": "2026-01-01T00:00:00Z", "end": "2026-06-01T00:00:00Z"},
    )
    assert zu_lang.status_code == 400


def test_busy_ohne_google_verbindung(client, make_user, login):
    login(make_user("TRAINER"))
    daten = client.get(
        "/api/v1/google/busy",
        query_string={"start": "2026-11-02T00:00:00Z", "end": "2026-11-03T00:00:00Z"},
    ).get_json()
    assert daten == {"connected": False, "busy": {}}
