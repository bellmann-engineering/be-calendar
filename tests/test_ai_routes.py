import unittest
import responses
from flask_jwt_extended import create_access_token
from app import create_app, db
from app.models import Role, User


class TestConfig:
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    JWT_SECRET_KEY = "test-jwt-secret-mit-ausreichender-laenge-2026"


class AIRoutesTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app(TestConfig)
        self.context = self.app.app_context()
        self.context.push()
        db.create_all()

        role = Role(name="CEO", permissions_json={})
        db.session.add(role)
        db.session.flush()

        self.user = User(
            email="ceo@test.com",
            password_hash="pw",
            first_name="C",
            last_name="O",
            role_id=role.id,
            is_active=True,
        )
        db.session.add(self.user)
        db.session.commit()
        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.context.pop()

    @responses.activate
    def test_ai_conflict_analysis(self):
        responses.add(
            responses.POST,
            "http://host.docker.internal:11434/api/generate",
            json={"response": "Simulierter KI-Bericht zur Konfliktlösung."},
            status=200,
        )

        token = create_access_token(
            identity=str(self.user.id), additional_claims={"role": "CEO"}
        )
        response = self.client.post(
            "/api/v1/ai/analyze",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "events": [
                    {
                        "title": "Test-Termin",
                        "start": "2026-09-05T10:00:00Z",
                        "end": "2026-09-05T11:00:00Z",
                    }
                ]
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("Bericht", response.json["analysis"])
