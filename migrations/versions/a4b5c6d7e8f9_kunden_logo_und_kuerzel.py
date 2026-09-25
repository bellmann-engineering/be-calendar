"""Kunden: Logo und Kürzel.

Revision ID: a4b5c6d7e8f9
Revises: f2a3b4c5d6e7
Create Date: 2026-09-25

Was passiert?
    ``customers`` bekommt
      * ``short_codes``     – Kürzel/Schreibweisen im Termintitel, z. B. "Comcave, CC"
      * ``logo_png``        – Logo als kleines PNG (bytea)
      * ``logo_updated_at`` – Upload-Zeitpunkt (Versionsnummer für den Browser-Cache)
"""

import sqlalchemy as sa
from alembic import op

revision = "a4b5c6d7e8f9"
down_revision = "f2a3b4c5d6e7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("customers", sa.Column("short_codes", sa.String(length=255), nullable=True))
    op.add_column("customers", sa.Column("logo_png", sa.LargeBinary(), nullable=True))
    op.add_column(
        "customers", sa.Column("logo_updated_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("customers", "logo_updated_at")
    op.drop_column("customers", "logo_png")
    op.drop_column("customers", "short_codes")
