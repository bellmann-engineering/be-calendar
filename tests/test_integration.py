"""
Tests für die Schnittstelle für andere Apps (/api/v1/integration): API-Key,
Überschneidungen je Tag, Urlaub eintragen.
"""

from datetime import datetime

import pytest

from app import db
from app.models import AuditLog, Event

KEY = "test-integration-key-" + "x" * 30
HEADERS = {"X-API-Key": KEY}


@pytest.fixture(autouse=True)
def api_key(app):
    app.config["INTEGRATION_API_KEY"] = KEY
    yield
    app.config["INTEGRATION_API_KEY"] = ""


def _event(user, title, start, end, all_day=False, deleted=False):
    e = Event(
        title=title,
        start_time=datetime.fromisoformat(start),
        end_time=datetime.fromisoformat(end),
        is_all_day=all_day,
        created_by_id=user.id,
        assigned_to_id=user.id,
        is_deleted=deleted,
    )
    db.session.add(e)
    db.session.commit()
    return e


def _avail(client, email, start, end, headers=HEADERS):
    return client.get(
        "/api/v1/integration/availability",
        query_string={"email": email, "start": start, "end": end},
        headers=headers,
    )


def test_ohne_schluessel_abgewiesen(client, make_user):
    user = make_user("TRAINER")
    assert _avail(client, user.email, "2026-10-12", "2026-10-14", headers={}).status_code == 401
    wrong = {"X-API-Key": "falsch"}
    assert _avail(client, user.email, "2026-10-12", "2026-10-14", headers=wrong).status_code == 401


def test_bearer_schluessel_funktioniert(client, make_user):
    user = make_user("TRAINER")
    resp = _avail(
        client, user.email, "2026-10-12", "2026-10-14", headers={"Authorization": f"Bearer {KEY}"}
    )
    assert resp.status_code == 200


def test_schnittstelle_aus_ohne_konfigurierten_schluessel(app, client, make_user):
    app.config["INTEGRATION_API_KEY"] = ""
    user = make_user("TRAINER")
    assert _avail(client, user.email, "2026-10-12", "2026-10-14").status_code == 404


def test_frei_liefert_leere_liste(client, make_user):
    user = make_user("TRAINER")
    body = _avail(client, user.email, "2026-10-12", "2026-10-14").get_json()
    assert body["conflicts"] == []


def test_ueberschneidungen_je_tag(client, make_user):
    user = make_user("TRAINER", email="Max@Example.com")
    # 12.10. 10-11 Uhr (Ortszeit = 08-09 UTC), mehrtägig 13.-15. (ganztägig, Ende exklusiv)
    _event(user, "Schulung", "2026-10-12T08:00:00+00:00", "2026-10-12T09:00:00+00:00")
    _event(
        user,
        "Messe",
        "2026-10-12T22:00:00+00:00",  # 13.10. 00:00 Ortszeit
        "2026-10-15T22:00:00+00:00",  # 16.10. 00:00 Ortszeit -> bis einschl. 15.10.
        all_day=True,
    )
    _event(user, "Gelöscht", "2026-10-12T08:00:00+00:00", "2026-10-12T09:00:00+00:00", deleted=True)
    other = make_user("TRAINER")
    _event(other, "Fremd", "2026-10-12T08:00:00+00:00", "2026-10-12T09:00:00+00:00")

    body = _avail(client, "max@example.com", "2026-10-12", "2026-10-14").get_json()
    days = {c["date"]: [e["title"] for e in c["events"]] for c in body["conflicts"]}
    assert days == {
        "2026-10-12": ["Schulung"],
        "2026-10-13": ["Messe"],
        "2026-10-14": ["Messe"],  # 15.10. liegt außerhalb des angefragten Zeitraums
    }
    messe = body["conflicts"][1]["events"][0]
    assert messe["is_all_day"] is True and messe["source"] == "calendar"


def test_ungueltige_eingaben(client, make_user):
    user = make_user("TRAINER")
    assert _avail(client, "niemand@example.com", "2026-10-12", "2026-10-14").status_code == 404
    assert _avail(client, user.email, "2026-10-14", "2026-10-12").status_code == 400
    assert _avail(client, user.email, "kaputt", "2026-10-12").status_code == 400
    assert _avail(client, "", "2026-10-12", "2026-10-14").status_code == 400
    inactive = make_user("TRAINER", is_active=False)
    assert _avail(client, inactive.email, "2026-10-12", "2026-10-14").status_code == 404


def test_urlaub_eintragen(client, make_user):
    user = make_user("TRAINER")
    resp = client.post(
        "/api/v1/integration/vacations",
        json={"email": user.email, "start": "2026-10-12", "end": "2026-10-14"},
        headers=HEADERS,
    )
    assert resp.status_code == 201
    event = resp.get_json()["event"]
    assert event["title"] == "Urlaub" and event["is_all_day"] is True
    assert event["assigned_to_id"] == user.id
    # 12.10. 00:00 bis 15.10. 00:00 Ortszeit (CEST = UTC+2)
    assert event["start_time"] == "2026-10-11T22:00:00+00:00"
    assert event["end_time"] == "2026-10-14T22:00:00+00:00"
    assert AuditLog.query.filter_by(action="CREATE_EVENT", user_id=user.id).count() == 1

    # Jetzt taucht der Urlaub in der Verfügbarkeit auf, an genau drei Tagen.
    body = _avail(client, user.email, "2026-10-01", "2026-10-31").get_json()
    assert [c["date"] for c in body["conflicts"]] == ["2026-10-12", "2026-10-13", "2026-10-14"]


def test_urlaub_eintragen_mit_eigenem_titel_und_fehlern(client, make_user):
    user = make_user("TRAINER")
    url = "/api/v1/integration/vacations"
    ok = client.post(
        url,
        json={
            "email": user.email,
            "start": "2026-10-12",
            "end": "2026-10-12",
            "title": "Urlaub (Antrag 7)",
        },
        headers=HEADERS,
    )
    assert ok.status_code == 201 and ok.get_json()["event"]["title"] == "Urlaub (Antrag 7)"
    bad_title = client.post(
        url,
        json={"email": user.email, "start": "2026-10-12", "end": "2026-10-12", "title": " "},
        headers=HEADERS,
    )
    assert bad_title.status_code == 400
    assert client.post(url, json={"email": user.email}, headers=HEADERS).status_code == 400
    assert client.post(url, json={}, headers=HEADERS).status_code == 400
    assert (
        client.post(
            url, json={"email": user.email, "start": "2026-10-12", "end": "2026-10-12"}
        ).status_code
        == 401
    )


def test_hinweis_im_layout_nur_ohne_schluessel(app, client, make_user, login):
    """Der Warnhinweis steckt im Layout, solange INTEGRATION_API_KEY fehlt (nicht in Tests)."""
    user = make_user("ADMIN")
    login(user)
    assert b"INTEGRATION_API_KEY fehlt" not in client.get("/dashboard").data
