"""
Tests für Rückmeldungen (RSVP): Pflichtbegründung, Neu-Zuweisung, genau EINE Benachrichtigung.
"""

from app import db
from app.models import Event, Notification


def _create_assigned_event(client, csrf, trainer_id: int) -> int:
    response = client.post(
        "/api/v1/events",
        json={
            "title": "Workshop",
            "start_time": "2026-10-02T09:00:00+02:00",
            "end_time": "2026-10-02T10:00:00+02:00",
            "assigned_to_id": trainer_id,
        },
        headers=csrf(),
    )
    assert response.status_code == 201
    return response.get_json()["event"]["id"]


def test_ablehnung_braucht_begruendung_und_gibt_termin_frei(client, make_user, login, csrf):
    ceo = make_user("CEO")
    trainer = make_user("TRAINER")
    login(ceo)
    event_id = _create_assigned_event(client, csrf, trainer.id)
    client.post("/api/v1/auth/logout")

    login(trainer)
    no_reason = client.put(
        f"/api/v1/events/{event_id}/rsvp", json={"status": "DECLINED"}, headers=csrf()
    )
    assert no_reason.status_code == 400

    declined = client.put(
        f"/api/v1/events/{event_id}/rsvp",
        json={"status": "DECLINED", "rejection_reason": "<b>krank</b>"},
        headers=csrf(),
    )
    assert declined.status_code == 200

    db.session.expire_all()
    event = db.session.get(Event, event_id)
    assert event.assigned_to_id is None
    assert event.reallocation_required is True
    # Genau EINE Benachrichtigung an den Ersteller (früher zwei identische).
    leader_notifications = Notification.query.filter_by(
        user_id=ceo.id, type="REALLOCATION_REQUIRED"
    ).all()
    assert len(leader_notifications) == 1

    # Der CEO sieht den Ablehnungsgrund in der Terminliste – unverändert als Text
    # (das Escaping übernimmt das Frontend per textContent).
    client.post("/api/v1/auth/logout")
    login(ceo)
    listed = client.get("/api/v1/events").get_json()
    assert listed[0]["rejection_reason"] == "<b>krank</b>"


def test_fremde_einladung_kann_nicht_beantwortet_werden(client, make_user, login, csrf):
    ceo = make_user("CEO")
    trainer = make_user("TRAINER")
    other = make_user("TRAINER")
    login(ceo)
    event_id = _create_assigned_event(client, csrf, trainer.id)
    client.post("/api/v1/auth/logout")

    login(other)
    response = client.put(
        f"/api/v1/events/{event_id}/rsvp", json={"status": "ACCEPTED"}, headers=csrf()
    )
    assert response.status_code == 403
