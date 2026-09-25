"""Rückmeldungen (RSVP) und "neu zuweisen" entfernen – Termine werden verbindlich zugewiesen.

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
Create Date: 2026-09-25

Was passiert?
    Mitarbeiter sagen zu Terminen nicht zu oder ab, sie werden ihnen einfach
    zugewiesen. Damit entfallen die Tabelle ``event_rsvps`` (Status + Ablehnungsgrund)
    und die Markierung ``events.reallocation_required`` ("abgelehnt – neu zuweisen").
    Downgrade legt beides leer bzw. mit false wieder an.
"""

import sqlalchemy as sa
from alembic import op

revision = "f2a3b4c5d6e7"
down_revision = "e1f2a3b4c5d6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table("event_rsvps")
    op.drop_index("ix_events_reallocation_required", table_name="events", if_exists=True)
    op.drop_column("events", "reallocation_required")


def downgrade() -> None:
    op.add_column(
        "events",
        sa.Column("reallocation_required", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_events_reallocation_required", "events", ["reallocation_required"])
    op.create_table(
        "event_rsvps",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "event_id",
            sa.Integer(),
            sa.ForeignKey("events.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="PENDING"),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("event_id", "user_id", name="uq_event_rsvps_event_user"),
    )
    op.create_index("ix_event_rsvps_user_id", "event_rsvps", ["user_id"])
