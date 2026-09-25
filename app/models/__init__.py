"""
Datenmodelle (SQLAlchemy ORM) – jede Klasse entspricht einer PostgreSQL-Tabelle.

Übersicht und Beziehungen (FK = Fremdschlüssel):

    roles ──< users >── teams            (User.role_id -> roles, User.team_id -> teams)
                │  └── led_team           (Team.team_leader_id -> users)
                │
    customers ──< events >── users        (Event.customer_id, created_by_id, assigned_to_id)
                    │   └── parent_event  (Event.parent_event_id -> events, Serien/Ausnahmen)
                    └──< audit_logs  >── users   (unveränderliche Historie)
    users ──< notifications                      (In-App-Benachrichtigungen)
    google_connections (höchstens 1 Zeile)        (verbundenes Google-Konto, Token verschlüsselt)

Wer benutzt dieses Paket?
    Services (``app/services``) und Routen importieren von hier, z. B.
    ``from app.models import Event, User``. Alembic (``migrations/env.py``) liest über
    ``db.metadata`` alle Tabellen, deshalb müssen alle Models hier importiert werden.

Wichtig: Schemaänderungen immer über eine neue Alembic-Migration (``flask db migrate``),
niemals über ``db.create_all()``.
"""

from app.models.audit import AuditLog
from app.models.customer import Customer
from app.models.event import Event
from app.models.google_connection import GoogleConnection
from app.models.notification import Notification
from app.models.role import Role, RoleEnum
from app.models.team import Team
from app.models.user import User

__all__ = [
    "Role",
    "RoleEnum",
    "Team",
    "User",
    "Event",
    "Customer",
    "AuditLog",
    "Notification",
    "GoogleConnection",
]
