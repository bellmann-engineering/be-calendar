"""
Tests für Termine: Überschneidungen erlaubt, Zeitzonen, Sichtbarkeit, N+1.
"""

from contextlib import contextmanager

from sqlalchemy import event as sa_event

from app import db
from app.models import Customer, Event


def _event_payload(
    assignee_id=None, start="2026-10-01T10:00:00+02:00", end="2026-10-01T11:00:00+02:00", **extra
):
    payload = {"title": "Schulung", "start_time": start, "end_time": end, **extra}
    if assignee_id is not None:
        payload["assigned_to_id"] = assignee_id
    return payload


@contextmanager
def count_queries():
    """Zählt alle SQL-Statements, die innerhalb des with-Blocks an die DB gehen."""
    counter = {"n": 0}

    def _before(*_args, **_kwargs):
        counter["n"] += 1

    sa_event.listen(db.engine, "before_cursor_execute", _before)
    try:
        yield counter
    finally:
        sa_event.remove(db.engine, "before_cursor_execute", _before)


def test_ueberschneidungen_sind_erlaubt(client, make_user, login, csrf):
    """Keine Kollisionsprüfung: mehrere ganztägige und stundenweise Termine am selben Tag."""
    admin = make_user("ADMIN")
    trainer = make_user("TRAINER")
    login(admin)
    payloads = [
        _event_payload(trainer.id),
        _event_payload(
            trainer.id, start="2026-10-01T10:30:00+02:00", end="2026-10-01T12:00:00+02:00"
        ),
        _event_payload(
            trainer.id,
            start="2026-10-01T00:00:00+02:00",
            end="2026-10-02T00:00:00+02:00",
            is_all_day=True,
        ),
        _event_payload(
            trainer.id,
            start="2026-10-01T00:00:00+02:00",
            end="2026-10-02T00:00:00+02:00",
            is_all_day=True,
        ),
    ]
    for payload in payloads:
        assert client.post("/api/v1/events", json=payload, headers=csrf()).status_code == 201

    created = client.get(
        "/api/v1/events",
        query_string={"start": "2026-10-01T00:00:00+02:00", "end": "2026-10-02T00:00:00+02:00"},
    ).get_json()
    assert len(created) == 4
    # Verschieben auf einen belegten Zeitraum ist ebenfalls erlaubt.
    moved = client.put(
        f"/api/v1/events/{created[0]['id']}",
        json={"start_time": "2026-10-01T10:45:00+02:00", "end_time": "2026-10-01T11:15:00+02:00"},
        headers=csrf(),
    )
    assert moved.status_code == 200


def test_zeiten_werden_als_utc_gespeichert_und_mit_offset_ausgegeben(
    client, make_user, login, csrf
):
    admin = make_user("ADMIN")
    login(admin)
    # Naive Eingabe = deutsche Ortszeit (Sommerzeit, UTC+2).
    created = client.post(
        "/api/v1/events",
        json=_event_payload(start="2026-10-01T10:00", end="2026-10-01T11:00"),
        headers=csrf(),
    ).get_json()
    assert created["event"]["start_time"] == "2026-10-01T08:00:00+00:00"


def test_trainer_sieht_nur_eigene_termine(client, make_user, login, csrf):
    admin = make_user("ADMIN")
    t1 = make_user("TRAINER")
    t2 = make_user("TRAINER")
    login(admin)
    client.post("/api/v1/events", json=_event_payload(t1.id), headers=csrf())
    client.post("/api/v1/events", json=_event_payload(t2.id), headers=csrf())
    client.post("/api/v1/auth/logout")

    login(t1)
    events = client.get("/api/v1/events").get_json()
    assert [e["assigned_to_id"] for e in events] == [t1.id]


def test_zeitraumfilter_und_ungueltiger_zeitraum(client, make_user, login, csrf):
    admin = make_user("ADMIN")
    login(admin)
    client.post("/api/v1/events", json=_event_payload(), headers=csrf())
    inside = client.get(
        "/api/v1/events",
        query_string={"start": "2026-09-28T00:00:00+02:00", "end": "2026-10-05T00:00:00+02:00"},
    )
    assert len(inside.get_json()) == 1
    outside = client.get(
        "/api/v1/events",
        query_string={"start": "2026-11-01T00:00:00+01:00", "end": "2026-11-08T00:00:00+01:00"},
    )
    assert outside.get_json() == []
    assert client.get("/api/v1/events?start=kaputt&end=auch").status_code == 400


def test_terminliste_ohne_n_plus_1(client, make_user, login, csrf):
    """Die Anzahl der SQL-Abfragen darf NICHT mit der Anzahl der Termine wachsen."""
    admin = make_user("ADMIN")
    login(admin)

    def create_events(count: int, day: int) -> None:
        for i in range(count):
            customer = Customer(name=f"K{day}-{i}", color_hex="#123456")
            db.session.add(customer)
            db.session.flush()
            db.session.add(
                Event(
                    title=f"E{i}",
                    start_time=f"2026-10-{day:02d}T0{i}:00:00+00:00",
                    end_time=f"2026-10-{day:02d}T0{i}:30:00+00:00",
                    created_by_id=admin.id,
                    customer_id=customer.id,
                    reallocation_required=True,
                )
            )
        db.session.commit()

    create_events(2, day=1)
    with count_queries() as small:
        assert len(client.get("/api/v1/events").get_json()) == 2
    create_events(6, day=2)
    with count_queries() as large:
        assert len(client.get("/api/v1/events").get_json()) == 8
    assert small["n"] == large["n"]


def test_unbekannter_kunde_liefert_400_statt_500(client, make_user, login, csrf):
    admin = make_user("ADMIN")
    login(admin)
    response = client.post("/api/v1/events", json=_event_payload(customer_id=9999), headers=csrf())
    assert response.status_code == 400
    assert "Kunde" in response.get_json()["message"]


def test_benachrichtigung_und_mail_erst_nach_commit(client, make_user, login, csrf, sent_mails):
    admin = make_user("ADMIN")
    trainer = make_user("TRAINER")
    login(admin)
    client.post("/api/v1/events", json=_event_payload(trainer.id), headers=csrf())
    assert sent_mails == [(trainer.email, "[Bellmann Eng.] Neuer Termin zugewiesen")]
    # Ungültige Daten (unbekannter Kunde) -> nichts gespeichert -> keine weitere Mail.
    rejected = client.post(
        "/api/v1/events", json=_event_payload(trainer.id, customer_id=99999), headers=csrf()
    )
    assert rejected.status_code == 400
    assert len(sent_mails) == 1
