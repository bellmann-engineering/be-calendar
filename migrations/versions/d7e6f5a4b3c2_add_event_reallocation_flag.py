"""Kennzeichnet nach RSVP-Ablehnung neu zu besetzende Termine.

Revision ID: d7e6f5a4b3c2
Revises: c4d3e2f1a9b8
Create Date: 2026-09-03
"""

from alembic import op
import sqlalchemy as sa


revision = "d7e6f5a4b3c2"
down_revision = "c4d3e2f1a9b8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Ergänzt das Flag für die ausstehende Neu-Zuweisung."""
    with op.batch_alter_table("events", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "reallocation_required",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch_op.create_index(
            batch_op.f("ix_events_reallocation_required"),
            ["reallocation_required"],
            unique=False,
        )


def downgrade() -> None:
    """Entfernt das Flag für die ausstehende Neu-Zuweisung."""
    with op.batch_alter_table("events", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_events_reallocation_required"))
        batch_op.drop_column("reallocation_required")
