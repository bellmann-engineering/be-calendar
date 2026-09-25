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
        self.termine: dict[str, list] = {}
        self.fehler: dict[str, str] = {}
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

    def list_events(self, ids, *_args):
        return (
            {i: self.termine.get(i, []) for i in ids if i not in self.fehler},
            {i: self.fehler[i] for i in ids if i in self.fehler},
        )


@pytest.fixture()
def fake_google(monkeypatch):
    fake = FakeGoogle()
    cls = calendar_service.GoogleCalendarService
    monkeypatch.setattr(cls, "_get_thread_service", lambda self: object())
    monkeypatch.setattr(cls, "insert_event", fake.insert)
    monkeypatch.setattr(cls, "update_event", fake.update)
    monkeypatch.setattr(cls, "delete_event", fake.delete)
    monkeypatch.setattr(cls, "list_events", fake.list_events)
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


def test_ohne_kalender_kein_google_aufruf(client, make_user, login, csrf, fake_google):
    ceo = make_user("CEO")
    trainer = make_user("TRAINER")
    login(ceo)
    client.post("/api/v1/events", json=_termin(trainer.id), headers=csrf())
    assert fake_google.aufrufe == []


# ------------------------------------------------------------------ Google-Termine anzeigen
def _g(gid, start, ende, titel="Termin", ganztaegig=False):
    return {
        "id": gid,
        "title": titel,
        "start": start,
        "end": ende,
        "all_day": ganztaegig,
        "location": None,
        "html_link": None,
    }


_TAG = {"start": "2026-11-02T00:00:00Z", "end": "2026-11-03T00:00:00Z"}


def test_google_termine_respektieren_sichtbarkeit(client, make_user, login, fake_google):
    anna = make_user("TRAINER", google_calendar_id="anna@gmail.com")
    ben = make_user("TRAINER", google_calendar_id="ben@gmail.com")
    fake_google.termine = {
        "anna@gmail.com": [_g("a1", "2026-11-02T08:00:00Z", "2026-11-02T09:00:00Z")],
        "ben@gmail.com": [_g("b1", "2026-11-02T10:00:00Z", "2026-11-02T11:00:00Z")],
    }
    login(anna)
    daten = client.get(
        "/api/v1/google/events", query_string={**_TAG, "user_ids": f"{anna.id},{ben.id}"}
    ).get_json()
    # Ein Trainer sieht nur seinen eigenen Google-Kalender, nicht den von Ben.
    assert list(daten["events"].keys()) == [str(anna.id)]


def test_google_termine_parallel_und_ganztaegig(client, make_user, login, fake_google):
    """Mehrere ganztägige und gleichzeitige Termine kommen vollständig mit Titel an."""
    ceo = make_user("CEO")
    anna = make_user("TRAINER", google_calendar_id="anna@gmail.com")
    fake_google.termine = {
        "anna@gmail.com": [
            _g("s1", "2026-11-02", "2026-11-04", "Schulung A", ganztaegig=True),
            _g("s2", "2026-11-02", "2026-11-03", "Schulung B", ganztaegig=True),
            _g("t1", "2026-11-02T08:00:00Z", "2026-11-02T09:00:00Z", "Call"),
            _g("t2", "2026-11-02T08:30:00Z", "2026-11-02T09:30:00Z", "Review"),
        ]
    }
    login(ceo)
    daten = client.get(
        "/api/v1/google/events", query_string={**_TAG, "user_ids": str(anna.id)}
    ).get_json()
    assert daten["connected"] is True
    titel = [t["title"] for t in daten["events"][str(anna.id)]]
    assert titel == ["Schulung A", "Schulung B", "Call", "Review"]
    zu_lang = client.get(
        "/api/v1/google/events",
        query_string={"start": "2026-01-01T00:00:00Z", "end": "2026-06-01T00:00:00Z"},
    )
    assert zu_lang.status_code == 400


def test_von_der_app_uebertragene_termine_erscheinen_nicht_doppelt(
    client, make_user, login, csrf, fake_google
):
    ceo = make_user("CEO")
    anna = make_user("TRAINER", google_calendar_id="anna@gmail.com")
    login(ceo)
    # Die Attrappe vergibt beim Übertragen die Google-ID "g1".
    client.post("/api/v1/events", json=_termin(anna.id), headers=csrf())
    fake_google.termine = {
        "anna@gmail.com": [
            _g("g1", "2026-11-02T08:00:00Z", "2026-11-02T09:00:00Z", "App-Kopie"),
            _g("x1", "2026-11-02T12:00:00Z", "2026-11-02T13:00:00Z", "Eigener Termin"),
        ]
    }
    daten = client.get(
        "/api/v1/google/events", query_string={**_TAG, "user_ids": str(anna.id)}
    ).get_json()
    assert [t["title"] for t in daten["events"][str(anna.id)]] == ["Eigener Termin"]


def test_fehlender_lesezugriff_wird_gemeldet(client, make_user, login, fake_google):
    anna = make_user("TRAINER", google_calendar_id="anna@gmail.com")
    fake_google.fehler = {"anna@gmail.com": "Kein Lesezugriff auf den Google-Kalender."}
    login(anna)
    daten = client.get("/api/v1/google/events", query_string=_TAG).get_json()
    assert daten["events"] == {str(anna.id): []}
    assert "Lesezugriff" in daten["errors"][str(anna.id)]


def test_google_termine_ohne_verbindung(client, make_user, login):
    login(make_user("TRAINER"))
    daten = client.get("/api/v1/google/events", query_string=_TAG).get_json()
    assert daten == {"connected": False, "events": {}, "errors": {}}


def test_umwandlung_von_google_terminen():
    """Ganztägig (auch "Frei") bleibt drin; abgesagte und App-Kopien fallen raus."""
    umwandeln = calendar_service._termin_aus_google
    ganztags = umwandeln(
        {
            "id": "1",
            "summary": "Schulung",
            "transparency": "transparent",
            "start": {"date": "2026-11-09"},
            "end": {"date": "2026-11-14"},
        }
    )
    assert ganztags["all_day"] is True and ganztags["end"] == "2026-11-14"
    ohne_titel = umwandeln(
        {
            "id": "2",
            "start": {"dateTime": "2026-11-02T14:00:00+01:00"},
            "end": {"dateTime": "2026-11-02T14:30:00+01:00"},
        }
    )
    assert ohne_titel["title"] == "(Ohne Titel)" and ohne_titel["all_day"] is False
    assert umwandeln({"id": "3", "status": "cancelled"}) is None
    app_kopie = {
        "id": "4",
        "start": {"dateTime": "2026-11-02T14:00:00Z"},
        "end": {"dateTime": "2026-11-02T15:00:00Z"},
        "extendedProperties": {"private": {calendar_service.APP_MARKER_KEY: "1"}},
    }
    assert umwandeln(app_kopie) is None
