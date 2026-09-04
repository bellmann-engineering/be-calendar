"""Ergänzt erforderliche Qualifikationen für Termine.

Revision ID: e1f2a3b4c5d6
Revises: d7e6f5a4b3c2
Create Date: 2026-09-03
"""

from alembic import op
import sqlalchemy as sa


revision = "e1f2a3b4c5d6"
down_revision = "d7e6f5a4b3c2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Erstellt die Zuordnungstabelle zwischen Terminen und erforderlichen Skills."""
    op.create_table(
        "event_required_skills",
        sa.Column("event_id", sa.Integer(), nullable=False),
        sa.Column("skill_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["skill_id"], ["skills.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("event_id", "skill_id"),
    )


def downgrade() -> None:
    """Entfernt die Zuordnungstabelle für erforderliche Skills."""
    op.drop_table("event_required_skills")
