"""
Tests für Rechteentzug, Teams, Benachrichtigungen, Kunden und die Google-Kollision.
"""

from app import db
from app.models import Customer, Event, Team, User


def test_ceo_entzieht_admin_rechte_admin_darf_admin_nicht(client, make_user, login, csrf):
    ceo = make_user("CEO")
    admin_a = make_user("ADMIN")
    admin_b = make_user("ADMIN")

    login(admin_a)
    denied = client.put(f"/api/v1/auth/users/{admin_b.id}/revoke-role", headers=csrf())
    assert denied.status_code == 403
    client.post("/api/v1/auth/logout")

    login(ceo)
    ok = client.put(f"/api/v1/auth/users/{admin_b.id}/revoke-role", headers=csrf())
    assert ok.status_code == 200
    db.session.expire_all()
    assert db.session.get(User, admin_b.id).role.name == "TRAINER"
    assert client.put(f"/api/v1/auth/users/{ceo.id}/revoke-role", headers=csrf()).status_code == 403


def test_entzug_der_teamleitung_gibt_team_frei(client, make_user, make_team, login, csrf):
    ceo = make_user("CEO")
    leader = make_user("TEAM_LEADER")
    team = make_team("Montage", leader=leader)
    login(ceo)
    assert (
        client.put(f"/api/v1/auth/users/{leader.id}/revoke-tl", headers=csrf()).status_code == 200
    )
    db.session.expire_all()
    assert db.session.get(Team, team.id).team_leader_id is None


def test_team_anlegen_und_mitglied_zuordnen(client, make_user, login, csrf):
    ceo = make_user("CEO")
    leader = make_user("TEAM_LEADER")
    trainer = make_user("TRAINER")
    login(ceo)
    created = client.post(
        "/api/v1/teams", json={"name": "Service", "team_leader_id": leader.id}, headers=csrf()
    )
    assert created.status_code == 201
    team_id = created.get_json()["team"]["id"]
    duplicate = client.post("/api/v1/teams", json={"name": "service"}, headers=csrf())
    assert duplicate.status_code == 409
    wrong_role = client.post(
        "/api/v1/teams", json={"name": "X", "team_leader_id": trainer.id}, headers=csrf()
    )
    assert wrong_role.status_code == 400

    assigned = client.put(f"/api/v1/teams/{team_id}/members/{trainer.id}", headers=csrf())
    assert assigned.status_code == 200
    assert assigned.get_json()["user"]["team_id"] == team_id


def test_teamleitung_plant_nur_im_eigenen_team(client, make_user, make_team, login, csrf):
    leader = make_user("TEAM_LEADER")
    team = make_team("Team A", leader=leader)
    own = make_user("TRAINER", team=team)
    foreign = make_user("TRAINER")
    login(leader)
    base = {
        "title": "Einsatz",
        "start_time": "2026-10-05T09:00:00+02:00",
        "end_time": "2026-10-05T10:00:00+02:00",
    }
    ok = client.post("/api/v1/events", json={**base, "assigned_to_id": own.id}, headers=csrf())
    assert ok.status_code == 201
    denied = client.post(
        "/api/v1/events", json={**base, "assigned_to_id": foreign.id}, headers=csrf()
    )
    assert denied.status_code == 403


def test_benachrichtigungen_nur_eigene(client, make_user, login, csrf):
    admin = make_user("ADMIN")
    trainer = make_user("TRAINER")
    other = make_user("TRAINER")
    login(admin)
    client.post(
        "/api/v1/events",
        json={
            "title": "Info",
            "start_time": "2026-10-06T09:00:00+02:00",
            "end_time": "2026-10-06T10:00:00+02:00",
            "assigned_to_id": trainer.id,
        },
        headers=csrf(),
    )
    client.post("/api/v1/auth/logout")

    login(trainer)
    notifications = client.get("/api/v1/notifications").get_json()["notifications"]
    assert len(notifications) == 1
    notification_id = notifications[0]["id"]
    client.post("/api/v1/auth/logout")

    login(other)
    foreign = client.put(f"/api/v1/notifications/{notification_id}/read", headers=csrf())
    assert foreign.status_code == 404
    client.post("/api/v1/auth/logout")

    login(trainer)
    own = client.put(f"/api/v1/notifications/{notification_id}/read", headers=csrf())
    assert own.status_code == 200


def test_kunde_loeschen_behaelt_termine(client, make_user, login, csrf):
    ceo = make_user("CEO")
    login(ceo)
    customer_id = client.post(
        "/api/v1/customers", json={"name": "Kunde X", "color_hex": "#AABBCC"}, headers=csrf()
    ).get_json()["id"]
    updated = client.put(
        f"/api/v1/customers/{customer_id}", json={"color_hex": "#000000"}, headers=csrf()
    )
    assert updated.status_code == 200
    event_id = client.post(
        "/api/v1/events",
        json={
            "title": "Kundentermin",
            "start_time": "2026-10-07T09:00:00+02:00",
            "end_time": "2026-10-07T10:00:00+02:00",
            "customer_id": customer_id,
        },
        headers=csrf(),
    ).get_json()["event"]["id"]

    assert client.delete(f"/api/v1/customers/{customer_id}", headers=csrf()).status_code == 200
    db.session.expire_all()
    assert db.session.get(Customer, customer_id) is None
    assert db.session.get(Event, event_id).customer_id is None


def test_privater_google_termin_blockiert(client, make_user, login, csrf, monkeypatch):
    admin = make_user("ADMIN")
    trainer = make_user("TRAINER", google_calendar_id="trainer@example.com")
    monkeypatch.setattr(
        "app.services.calendar_service.GoogleCalendarService.get_busy_times",
        lambda self, *_args: [{"start": "2026-10-08T07:00:00Z", "end": "2026-10-08T09:00:00Z"}],
    )
    login(admin)
    response = client.post(
        "/api/v1/events",
        json={
            "title": "Kollidiert privat",
            "start_time": "2026-10-08T09:00:00+02:00",
            "end_time": "2026-10-08T10:00:00+02:00",
            "assigned_to_id": trainer.id,
        },
        headers=csrf(),
    )
    assert response.status_code == 409
    assert "Google" in response.get_json()["message"]
