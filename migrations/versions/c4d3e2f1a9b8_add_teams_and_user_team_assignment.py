"""Fügt organisatorische Teams für teambezogene Zugriffsregeln hinzu.

Revision ID: c4d3e2f1a9b8
Revises: b02c2c99c1a7
Create Date: 2026-09-03
"""

from alembic import op
import sqlalchemy as sa

revision = "c4d3e2f1a9b8"
down_revision = "b02c2c99c1a7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Erstellt Teams und ergänzt die optionale Teamzuordnung der Benutzer."""
    op.create_table(
        "teams",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("team_leader_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["team_leader_id"],
            ["users.id"],
            name="fk_teams_team_leader_id",
            use_alter=True,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(sa.Column("team_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key("fk_users_team_id", "teams", ["team_id"], ["id"])
        batch_op.create_index(batch_op.f("ix_users_team_id"), ["team_id"], unique=False)


def downgrade() -> None:
    """Entfernt die Teamzuordnung und die Teams rückstandsfrei."""
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_users_team_id"))
        batch_op.drop_constraint("fk_users_team_id", type_="foreignkey")
        batch_op.drop_column("team_id")
    op.drop_table("teams")
