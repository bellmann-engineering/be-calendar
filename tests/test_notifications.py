"""Integrationstests für das Benachrichtigungssystem (Modul D)."""

import unittest
from flask_jwt_extended import create_access_token

from app import create_app, db
from app.models import Notification, Role, User


class TestConfig:
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    JWT_SECRET_KEY = "test-jwt-secret-mit-ausreichender-laenge-2026"


class NotificationTestCase(unittest.TestCase):

    def setUp(self) -> None:
        self.app = create_app(TestConfig)
        self.context = self.app.app_context()
        self.context.push()
        db.create_all()

        role = Role(name="CEO", permissions_json={})
        db.session.add(role)
        db.session.flush()

        self.user = User(
            email="test@example.com",
            password_hash="pw",
            first_name="Test",
            last_name="User",
            role_id=role.id,
            is_active=True,
        )
        db.session.add(self.user)
        db.session.commit()

        self.client = self.app.test_client()

    def tearDown(self) -> None:
        db.session.remove()
        db.drop_all()
        self.context.pop()

    def test_notification_creation_and_retrieval(self) -> None:
        token = create_access_token(
            identity=str(self.user.id), additional_claims={"role": "CEO"}
        )
        headers = {"Authorization": f"Bearer {token}"}

        notification = Notification(
            user_id=self.user.id,
            title="Test Title",
            message="Test Message",
            type="EVENT_ASSIGNED",
        )
        db.session.add(notification)
        db.session.commit()

        response = self.client.get("/api/v1/notifications", headers=headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json["notifications"]), 1)
        self.assertFalse(response.json["notifications"][0]["is_read"])

        notification_id = response.json["notifications"][0]["id"]
        response = self.client.put(
            f"/api/v1/notifications/{notification_id}/read", headers=headers
        )
        self.assertEqual(response.status_code, 200)

        n = db.session.get(Notification, notification_id)
        self.assertTrue(n.is_read)


if __name__ == "__main__":
    unittest.main()
