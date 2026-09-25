"""Glocke: neue Google-Termine erkennen, Sprung zum Tag.

Revision ID: b5c6d7e8f9a0
Revises: a4b5c6d7e8f9
Create Date: 2026-09-25

Was passiert?
    * Neue Tabelle ``google_seen_events``: bereits bekannte Google-Termine je Mitarbeiter.
    * ``users.google_watch_calendar_id`` / ``google_watch_checked_at``: für welchen
      Kalender die Liste gilt und wann zuletzt geprüft wurde.
    * ``notifications.target_date``: Tag des Termins (Klick springt im Kalender dorthin).
"""

import sqlalchemy as sa
from alembic import op

revision = "b5c6d7e8f9a0"
down_revision = "a4b5c6d7e8f9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "google_seen_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event_key", sa.String(length=300), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "event_key", name="uq_google_seen_events_user_key"),
    )
    op.add_column("users", sa.Column("google_watch_calendar_id", sa.String(255), nullable=True))
    op.add_column(
        "users", sa.Column("google_watch_checked_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("notifications", sa.Column("target_date", sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column("notifications", "target_date")
    op.drop_column("users", "google_watch_checked_at")
    op.drop_column("users", "google_watch_calendar_id")
    op.drop_table("google_seen_events")
