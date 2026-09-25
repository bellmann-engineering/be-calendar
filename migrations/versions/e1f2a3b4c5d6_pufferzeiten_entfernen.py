"""Pufferzeiten entfernen (es gibt keine Kollisionsprüfung mehr).

Revision ID: e1f2a3b4c5d6
Revises: c3e5a7b9d1f2
Create Date: 2026-09-25

Was passiert?
    Die Spalten ``events.buffer_before_mins`` und ``events.buffer_after_mins`` dienten
    nur der Kollisionsprüfung. Termine dürfen sich überschneiden (mehrere ganztägige und
    stundenweise Termine am selben Tag), daher werden sie gelöscht.
    Downgrade legt sie wieder an (Werte 0).
"""

import sqlalchemy as sa
from alembic import op

revision = "e1f2a3b4c5d6"
down_revision = "c3e5a7b9d1f2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("events", "buffer_before_mins")
    op.drop_column("events", "buffer_after_mins")


def downgrade() -> None:
    op.add_column(
        "events",
        sa.Column("buffer_after_mins", sa.Integer(), nullable=True, server_default="0"),
    )
    op.add_column(
        "events",
        sa.Column("buffer_before_mins", sa.Integer(), nullable=True, server_default="0"),
    )
