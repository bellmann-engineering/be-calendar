"""
Tests für die Benutzerverwaltung – vor allem die Rollen-Hierarchie (Privilege Escalation).

Früher konnte ein ADMIN sich selbst zum CEO machen, das CEO-Passwort ändern oder per CSV
CEO-Konten anlegen. Diese Tests stellen sicher, dass das nie wieder möglich ist.
"""

import io

from app import db
from app.models import User


def test_admin_kann_sich_nicht_zum_ceo_befoerdern(client, make_user, login, csrf):
    admin = make_user("ADMIN")
    login(admin)
    response = client.put(f"/api/v1/auth/users/{admin.id}", json={"role": "CEO"}, headers=csrf())
    assert response.status_code == 403
    db.session.expire_all()
    assert db.session.get(User, admin.id).role.name == "ADMIN"


def test_admin_darf_eigenen_namen_aendern(client, make_user, login, csrf):
    admin = make_user("ADMIN")
    login(admin)
    response = client.put(
        f"/api/v1/auth/users/{admin.id}",
        json={"first_name": "Neu", "role": "ADMIN"},
        headers=csrf(),
    )
    assert response.status_code == 200


def test_admin_kann_ceo_weder_aendern_noch_sperren_noch_loeschen(client, make_user, login, csrf):
    ceo = make_user("CEO")
    admin = make_user("ADMIN")
    login(admin)
    assert (
        client.put(
            f"/api/v1/auth/users/{ceo.id}",
            json={"password": "Uebernahme-Passwort-1"},
            headers=csrf(),
        ).status_code
        == 403
    )
    assert client.put(f"/api/v1/auth/{ceo.id}/status", headers=csrf()).status_code == 403
    assert client.delete(f"/api/v1/auth/users/{ceo.id}", headers=csrf()).status_code == 403


def test_admin_darf_nur_trainer_und_teamleitung_anlegen(client, make_user, login, csrf):
    admin = make_user("ADMIN")
    login(admin)
    base = {"password": "Sicheres-Passwort-123", "first_name": "X", "last_name": "Y"}
    as_admin = client.post(
        "/api/v1/auth/users",
        json={**base, "email": "neu1@example.com", "role": "ADMIN"},
        headers=csrf(),
    )
    assert as_admin.status_code == 403
    as_trainer = client.post(
        "/api/v1/auth/users",
        json={**base, "email": "neu2@example.com", "role": "TRAINER"},
        headers=csrf(),
    )
    assert as_trainer.status_code == 201


def test_ceo_darf_admins_anlegen(client, make_user, login, csrf):
    ceo = make_user("CEO")
    login(ceo)
    response = client.post(
        "/api/v1/auth/users",
        json={
            "email": "admin-neu@example.com",
            "password": "Sicheres-Passwort-123",
            "first_name": "A",
            "last_name": "B",
            "role": "ADMIN",
        },
        headers=csrf(),
    )
    assert response.status_code == 201


def test_trainer_sieht_keine_benutzerliste(client, make_user, login):
    trainer = make_user("TRAINER")
    login(trainer)
    assert client.get("/api/v1/auth").status_code == 403


def test_teamleitung_sieht_nur_eigenes_team(client, make_user, make_team, login):
    leader = make_user("TEAM_LEADER")
    team = make_team("Team A", leader=leader)
    member = make_user("TRAINER", team=team)
    make_user("TRAINER")  # fremd, ohne Team
    login(leader)
    emails = {u["email"] for u in client.get("/api/v1/auth").get_json()}
    assert emails == {leader.email, member.email}


def test_csv_import_mit_hierarchie_und_deutschen_fehlern(
    client, make_user, login, csrf, sent_mails
):
    make_user("TRAINER", email="vorhanden@example.com")
    admin = make_user("ADMIN")
    login(admin)
    csv_content = (
        "email,first_name,last_name,role\n"
        "neu@example.com,Neu,Person,TRAINER\n"
        "vorhanden@example.com,Doppelt,Da,TRAINER\n"
        "chef@example.com,Böser,Chef,CEO\n"
        ",Ohne,Mail,TRAINER\n"
        "neu@example.com,Doppelt,InDatei,TRAINER\n"
    )
    response = client.post(
        "/api/v1/auth/csv",
        data={"file": (io.BytesIO(csv_content.encode("utf-8")), "users.csv")},
        headers=csrf(),
        content_type="multipart/form-data",
    )
    assert response.status_code == 200
    body = response.get_json()
    assert body["message"] == "1 Benutzer importiert."
    assert "Zeile 3: E-Mail vorhanden@example.com existiert bereits." in body["errors"]
    assert any(e.startswith("Zeile 4:") and "Admin" in e for e in body["errors"])
    assert "Zeile 5: E-Mail fehlt." in body["errors"]
    assert "Zeile 6: E-Mail neu@example.com existiert bereits." in body["errors"]
    # Einladung wurde nach dem Commit verschickt.
    assert sent_mails == [
        ("neu@example.com", "Dein Zugang zum Kalender der Bellmann Engineering GmbH")
    ]


def test_csv_import_lehnt_nicht_utf8_ab(client, make_user, login, csrf):
    ceo = make_user("CEO")
    login(ceo)
    response = client.post(
        "/api/v1/auth/csv",
        data={"file": (io.BytesIO("email\nmüller@example.com\n".encode("latin-1")), "u.csv")},
        headers=csrf(),
        content_type="multipart/form-data",
    )
    assert response.status_code == 400
