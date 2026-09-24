"""Google-OAuth-Verbindung und Kalender-Synchronisierung.

Revision ID: c3e5a7b9d1f2
Revises: a7c9e2d4f6b8
Create Date: 2026-09-25

Was passiert?
    1. Neue Tabelle ``google_connections``: das einmalig verbundene Google-Konto eines
       CEO/ADMIN mit verschlüsseltem Refresh-Token (siehe app/models/google_connection.py).
    2. Neue Spalte ``events.google_sync_calendar_id``: in welchem Google-Kalender die
       gespiegelte Kopie eines Termins liegt. Bestehende Kopien (``google_event_id``
       gesetzt) bekommen den Kalender ihres aktuell zugewiesenen Mitarbeiters – das war
       bisher die einzige Stelle, an die gespiegelt wurde.
"""

import sqlalchemy as sa
from alembic import op

revision = "c3e5a7b9d1f2"
down_revision = "a7c9e2d4f6b8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "google_connections",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account_email", sa.String(length=255), nullable=True),
        sa.Column("refresh_token_enc", sa.Text(), nullable=False),
        sa.Column("scopes", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "connected_by_id",
            sa.Integer(),
            sa.ForeignKey(
                "users.id", name="fk_google_connections_connected_by_id", ondelete="SET NULL"
            ),
            nullable=True,
        ),
        sa.Column("connected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_google_connections_connected_by_id", "google_connections", ["connected_by_id"]
    )

    op.add_column(
        "events", sa.Column("google_sync_calendar_id", sa.String(length=255), nullable=True)
    )
    # Bestehende Google-Kopien dem Kalender des zugewiesenen Mitarbeiters zuordnen.
    op.execute(
        "UPDATE events SET google_sync_calendar_id = users.google_calendar_id "
        "FROM users WHERE events.assigned_to_id = users.id "
        "AND events.google_event_id IS NOT NULL AND users.google_calendar_id IS NOT NULL"
    )


def downgrade() -> None:
    op.drop_column("events", "google_sync_calendar_id")
    op.drop_index("ix_google_connections_connected_by_id", table_name="google_connections")
    op.drop_table("google_connections")
