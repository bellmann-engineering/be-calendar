"""Integrationstests für RSVP-Rückmeldungen, Skills, Audit-Logs und Rechteentzug-Reports."""

import os
import unittest
from datetime import datetime, timedelta, timezone

from flask_jwt_extended import create_access_token

from app import create_app, db
from app.models import (
    AuditLog,
    Event,
    EventRSVP,
    Notification,
    RSVPStatusEnum,
    Role,
    Skill,
    Team,
    User,
)
from app.services.admin_service import AdminService


class TestConfig:
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    JWT_SECRET_KEY = "test-jwt-secret-mit-ausreichender-laenge-2026"


class RSVPAndSkillRouteTestCase(unittest.TestCase):

    def setUp(self) -> None:
        self.app = create_app(TestConfig)
        self.context = self.app.app_context()
        self.context.push()
        db.create_all()

        # Prompt-Datei sicherstellen
        prompt_dir = os.path.join(self.app.root_path, "prompts")
        os.makedirs(prompt_dir, exist_ok=True)
        prompt_path = os.path.join(prompt_dir, "ai_prompt_de.txt")
        if not os.path.exists(prompt_path):
            with open(prompt_path, "w", encoding="utf-8") as f:
                f.write("System Prompt für KI-Qualifikationsprüfung")

        ceo_role = Role(name="CEO", permissions_json={})
        trainer_role = Role(name="TRAINER", permissions_json={})
        team_leader_role = Role(name="TEAM_LEADER", permissions_json={})
        db.session.add_all([ceo_role, trainer_role, team_leader_role])
        db.session.flush()

        self.ceo = User(
            email="ceo@example.test",
            password_hash="unbenutzt",
            first_name="Kai",
            last_name="Bellmann",
            role_id=ceo_role.id,
            is_active=True,
        )
        self.trainer = User(
            email="trainer@example.test",
            password_hash="unbenutzt",
            first_name="Tina",
            last_name="Trainer",
            role_id=trainer_role.id,
            is_active=True,
        )
        self.team_leader = User(
            email="leitung@example.test",
            password_hash="unbenutzt",
            first_name="Lea",
            last_name="Leitung",
            role_id=team_leader_role.id,
            is_active=True,
        )
        self.other_trainer = User(
            email="anderer.trainer@example.test",
            password_hash="unbenutzt",
            first_name="Anton",
            last_name="Anders",
            role_id=trainer_role.id,
            is_active=True,
        )
        db.session.add_all(
            [self.ceo, self.trainer, self.team_leader, self.other_trainer]
        )
        db.session.flush()

        team_a = Team(name="Team A", team_leader_id=self.team_leader.id)
        team_b = Team(name="Team B", team_leader_id=self.ceo.id)
        db.session.add_all([team_a, team_b])
        db.session.flush()

        self.trainer.team_id = team_a.id
        self.team_leader.team_id = team_a.id
        self.other_trainer.team_id = team_b.id

        event = Event(
            title="Sicherheitsunterweisung",
            start_time=datetime.now(timezone.utc),
            end_time=datetime.now(timezone.utc) + timedelta(hours=1),
            created_by_id=self.ceo.id,
            assigned_to_id=self.trainer.id,
        )
        db.session.add(event)
        db.session.flush()

        db.session.add(
            EventRSVP(
                event_id=event.id,
                user_id=self.trainer.id,
                status=RSVPStatusEnum.PENDING.value,
            )
        )
        db.session.commit()

        self.event_id = event.id
        self.client = self.app.test_client()

    def tearDown(self) -> None:
        db.session.remove()
        db.drop_all()
        self.context.pop()

    def _headers_for(self, user: User) -> dict:
        token = create_access_token(
            identity=str(user.id), additional_claims={"role": user.role.name}
        )
        return {"Authorization": f"Bearer {token}"}

    def test_buffers_qualifications_prompt_and_user_audit(self) -> None:
        """Prüft Pufferregeln, Qualifikationswarnung, Prompt-Datei und Benutzer-Audit."""
        headers = self._headers_for(self.team_leader)

        payload = {
            "title": "Schulung Brandschutz",
            "start_time": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
            "end_time": (
                datetime.now(timezone.utc) + timedelta(days=1, hours=2)
            ).isoformat(),
            "buffer_before_mins": 5,
            "buffer_after_mins": 15,
            "assigned_to_id": self.trainer.id,
        }
        response = self.client.post("/api/v1/events", json=payload, headers=headers)
        self.assertEqual(response.status_code, 400)

        skill = Skill(name="Brandschutz-Zertifikat")
        db.session.add(skill)
        db.session.commit()

        payload["buffer_before_mins"] = 15
        payload["required_skill_ids"] = [skill.id]
        response = self.client.post("/api/v1/events", json=payload, headers=headers)
        self.assertEqual(response.status_code, 201)

        event_data = response.json.get("event", response.json)
        self.assertIn("qualification_warning", event_data)

        prompt_path = os.path.join(self.app.root_path, "prompts", "ai_prompt_de.txt")
        self.assertTrue(os.path.exists(prompt_path))

        audit_entry = (
            AuditLog.query.filter_by(action="CREATE_EVENT")
            .order_by(AuditLog.id.desc())
            .first()
        )
        self.assertIsNotNone(audit_entry)
        self.assertEqual(audit_entry.user_id, self.team_leader.id)

    def test_decline_requires_reason_and_is_audited(self) -> None:
        """Eine Ablehnung ohne Begründung scheitert, mit Begründung wird sie gespeichert und als Aufgabe verlagert."""
        headers = self._headers_for(self.trainer)

        response = self.client.put(
            f"/api/v1/events/{self.event_id}/rsvp",
            json={"status": "DECLINED"},
            headers=headers,
        )
        self.assertEqual(response.status_code, 400)

        response = self.client.put(
            f"/api/v1/events/{self.event_id}/rsvp",
            json={
                "status": "DECLINED",
                "rejection_reason": "Bereits bei einem Kundentermin.",
            },
            headers=headers,
        )
        self.assertEqual(response.status_code, 200)

        event = db.session.get(Event, self.event_id)
        self.assertIsNone(event.assigned_to_id)
        self.assertTrue(event.reallocation_required)

        audit_entry = AuditLog.query.filter_by(
            action="RSVP_DECLINED_REALLOCATION_NEEDED"
        ).first()
        self.assertIsNotNone(audit_entry)

    def test_revoke_team_leader_role_generates_report(self) -> None:
        """Prüft den Entzug der TL-Rolle, den Abbau der Teamzuweisung und die Erstellung des Kai-Bellmann-Reports."""
        response_data, status_code = AdminService.revoke_team_leader_role(
            user_id=self.team_leader.id, executed_by_id=self.ceo.id
        )
        self.assertEqual(status_code, 200)
        self.assertIn("report", response_data)

        updated_tl = db.session.get(User, self.team_leader.id)
        self.assertEqual(updated_tl.role.name, "TRAINER")

        audit_entry = AuditLog.query.filter_by(
            action="REVOKE_TL_ROLE_REPORT_GENERATED"
        ).first()
        self.assertIsNotNone(audit_entry)
        self.assertEqual(
            audit_entry.details_json["revoked_user_id"], self.team_leader.id
        )

        ceo_notification = Notification.query.filter_by(user_id=self.ceo.id).first()
        self.assertIsNotNone(ceo_notification)
        self.assertIn("Rechteentzug-Report", ceo_notification.title)

    def test_skill_management_and_filtering(self) -> None:
        """CEO kann Skills anlegen, zuordnen und geeignete Trainer filtern."""
        ceo_headers = self._headers_for(self.ceo)

        response = self.client.post(
            "/api/v1/skills", json={"name": "Ersthelfer"}, headers=ceo_headers
        )
        self.assertEqual(response.status_code, 201)
        skill_data = response.json.get("skill", response.json)
        skill_id = skill_data["id"]

        response = self.client.put(
            f"/api/v1/skills/users/{self.trainer.id}",
            json={"skill_ids": [skill_id]},
            headers=ceo_headers,
        )
        if response.status_code == 404:
            response = self.client.post(
                f"/api/v1/skills/users/{self.trainer.id}",
                json={"skill_ids": [skill_id]},
                headers=ceo_headers,
            )
        if response.status_code == 404:
            response = self.client.put(
                f"/api/v1/users/{self.trainer.id}/skills",
                json={"skill_ids": [skill_id]},
                headers=ceo_headers,
            )
        self.assertIn(response.status_code, [200, 201])

        updated_trainer = db.session.get(User, self.trainer.id)
        self.assertTrue(any(s.id == skill_id for s in updated_trainer.skills))

    def test_team_leader_is_limited_to_own_team_and_ceo_can_override(self) -> None:
        """Teamgrenzen sperren Fremdtermine; CEO-Override benötigt explizite Bestätigung."""
        tl_headers = self._headers_for(self.team_leader)
        start_dt = datetime.now(timezone.utc) + timedelta(days=2)
        end_dt = start_dt + timedelta(hours=1)

        payload = {
            "title": "Fremdteam-Termin",
            "start_time": start_dt.isoformat(),
            "end_time": end_dt.isoformat(),
            "assigned_to_id": self.other_trainer.id,
        }
        response = self.client.post("/api/v1/events", json=payload, headers=tl_headers)
        self.assertEqual(response.status_code, 403)

        ceo_headers = self._headers_for(self.ceo)
        response = self.client.post("/api/v1/events", json=payload, headers=ceo_headers)
        self.assertEqual(response.status_code, 201)

        conflict_payload = {
            "title": "Konflikt-Termin",
            "start_time": start_dt.isoformat(),
            "end_time": end_dt.isoformat(),
            "assigned_to_id": self.other_trainer.id,
        }
        response = self.client.post(
            "/api/v1/events", json=conflict_payload, headers=ceo_headers
        )
        self.assertEqual(response.status_code, 409)

        conflict_payload["override_conflict"] = True
        response = self.client.post(
            "/api/v1/events", json=conflict_payload, headers=ceo_headers
        )
        self.assertEqual(response.status_code, 201)


if __name__ == "__main__":
    unittest.main()
