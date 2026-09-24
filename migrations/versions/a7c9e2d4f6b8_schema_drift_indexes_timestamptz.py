"""Schema-Drift beheben, fehlende Indizes, RSVP-Eindeutigkeit, timestamptz.

Revision ID: a7c9e2d4f6b8
Revises: bcf52e20a906
Create Date: 2026-09-24

WARUM gibt es diese Migration?
    Die Models enthielten Tabellen/Spalten, die KEINE Migration je angelegt hat
    (customers, events.customer_id, meeting_link, is_all_day, google_event_id,
    recurrence_rule, parent_event_id, users.google_calendar_id). Eine frisch per
    ``flask db upgrade`` erzeugte Datenbank war dadurch unbrauchbar (500er bei jeder
    Terminabfrage). Bestehende Installationen haben diese Objekte evtl. schon (früher
    per db.create_all() entstanden).

DESHALB ist jede Operation IDEMPOTENT: Vor dem Anlegen wird per SQLAlchemy-Inspector
geprüft, ob Tabelle/Spalte/Index schon existiert. So läuft die Migration auf einer
leeren UND auf einer "gewachsenen" Datenbank fehlerfrei durch.

Was passiert im Einzelnen?
    1. Fehlende Tabelle ``customers`` und fehlende Spalten ergänzen.
    2. Alle Zeitstempel von ``timestamp`` auf ``timestamptz`` umstellen:
       * events.start_time/end_time wurden bisher als deutsche Ortszeit ("Wanduhr")
         gespeichert -> Umrechnung mit ``AT TIME ZONE 'Europe/Berlin'``
         (überschreibbar per Umgebungsvariable LEGACY_EVENT_TIMEZONE).
       * Alle anderen Zeitstempel (created_at, updated_at, deleted_at, timestamp) waren
         bereits UTC -> ``AT TIME ZONE 'UTC'``.
    3. Fehlende Indizes auf Fremdschlüsseln + zusammengesetzte Indizes für die
       häufigsten Abfragen (Kollisionsprüfung, Benachrichtigungen).
    4. RSVP-Duplikate bereinigen (neuester Eintrag gewinnt) und UNIQUE(event_id, user_id)
       anlegen.

Nur PostgreSQL (AT TIME ZONE, DELETE ... USING). Vor dem Upgrade in Produktion: Backup!
    docker compose exec db pg_dump -U $POSTGRES_USER $POSTGRES_DB > backup.sql
"""

import os

import sqlalchemy as sa
from alembic import op

revision = "a7c9e2d4f6b8"
down_revision = "bcf52e20a906"
branch_labels = None
depends_on = None

LEGACY_EVENT_TZ = os.getenv("LEGACY_EVENT_TIMEZONE", "Europe/Berlin")

# (Tabelle, Spalte, Zeitzone, in der die alten naiven Werte gemeint waren)
TIMESTAMP_COLUMNS = [
    ("events", "start_time", LEGACY_EVENT_TZ),
    ("events", "end_time", LEGACY_EVENT_TZ),
    ("events", "deleted_at", "UTC"),
    ("events", "created_at", "UTC"),
    ("events", "updated_at", "UTC"),
    ("users", "created_at", "UTC"),
    ("audit_logs", "timestamp", "UTC"),
    ("event_rsvps", "updated_at", "UTC"),
    ("notifications", "created_at", "UTC"),
]

# (Indexname, Tabelle, Spalten)
INDEXES = [
    ("ix_events_customer_id", "events", ["customer_id"]),
    ("ix_events_created_by_id", "events", ["created_by_id"]),
    ("ix_events_assigned_to_id", "events", ["assigned_to_id"]),
    ("ix_events_parent_event_id", "events", ["parent_event_id"]),
    ("ix_events_assignee_active_start", "events", ["assigned_to_id", "is_deleted", "start_time"]),
    ("ix_event_rsvps_user_id", "event_rsvps", ["user_id"]),
    ("ix_audit_logs_user_id", "audit_logs", ["user_id"]),
    ("ix_audit_logs_event_id", "audit_logs", ["event_id"]),
    ("ix_users_role_id", "users", ["role_id"]),
    ("ix_teams_team_leader_id", "teams", ["team_leader_id"]),
    ("ix_notifications_user_created", "notifications", ["user_id", "created_at"]),
]

RSVP_UNIQUE = "uq_event_rsvps_event_user"


# ----------------------------------------------------------------------------- Helfer
def _inspector() -> sa.engine.reflection.Inspector:
    """Frischer Inspector (er cached – nach Änderungen daher neu erzeugen)."""
    return sa.inspect(op.get_bind())


def _has_table(name: str) -> bool:
    return _inspector().has_table(name)


def _columns(table: str) -> dict[str, dict]:
    return {col["name"]: col for col in _inspector().get_columns(table)}


def _has_index(table: str, name: str) -> bool:
    return any(ix["name"] == name for ix in _inspector().get_indexes(table))


def _has_unique(table: str, name: str) -> bool:
    return any(uc["name"] == name for uc in _inspector().get_unique_constraints(table))


def _add_column_if_missing(table: str, column: sa.Column) -> None:
    if column.name not in _columns(table):
        op.add_column(table, column)


# ----------------------------------------------------------------------------- Upgrade
def upgrade() -> None:
    # 1) Tabelle customers ------------------------------------------------------------
    if not _has_table("customers"):
        op.create_table(
            "customers",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("name", sa.String(length=150), nullable=False),
            sa.Column("email", sa.String(length=150), nullable=True),
            sa.Column("color_hex", sa.String(length=7), nullable=True),
        )

    # 2) Fehlende Spalten ---------------------------------------------------------------
    _add_column_if_missing("users", sa.Column("google_calendar_id", sa.String(255), nullable=True))
    _add_column_if_missing("events", sa.Column("meeting_link", sa.String(500), nullable=True))
    _add_column_if_missing("events", sa.Column("google_event_id", sa.String(255), nullable=True))
    _add_column_if_missing(
        "events",
        # server_default füllt bestehende Zeilen, damit NOT NULL sofort gilt.
        sa.Column("is_all_day", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    _add_column_if_missing("events", sa.Column("customer_id", sa.Integer(), nullable=True))
    _add_column_if_missing("events", sa.Column("recurrence_rule", sa.String(100), nullable=True))
    _add_column_if_missing("events", sa.Column("parent_event_id", sa.Integer(), nullable=True))

    # Fremdschlüssel nur anlegen, wenn für die Spalte noch keiner existiert.
    existing_fk_columns = {
        tuple(fk["constrained_columns"]) for fk in _inspector().get_foreign_keys("events")
    }
    if ("customer_id",) not in existing_fk_columns:
        op.create_foreign_key(
            "fk_events_customer_id", "events", "customers", ["customer_id"], ["id"]
        )
    if ("parent_event_id",) not in existing_fk_columns:
        op.create_foreign_key(
            "fk_events_parent_event_id",
            "events",
            "events",
            ["parent_event_id"],
            ["id"],
            ondelete="CASCADE",
        )

    # Altlast aus c4d3e2f1a9b8: Dort stand der FK teams.team_leader_id mit use_alter=True
    # in op.create_table() – Alembic legt solche FKs dabei NICHT an. Hier nachholen.
    team_fk_columns = {
        tuple(fk["constrained_columns"]) for fk in _inspector().get_foreign_keys("teams")
    }
    if ("team_leader_id",) not in team_fk_columns:
        op.create_foreign_key(
            "fk_teams_team_leader_id", "teams", "users", ["team_leader_id"], ["id"]
        )

    # 3) timestamp -> timestamptz -------------------------------------------------------
    for table, column, source_tz in TIMESTAMP_COLUMNS:
        col = _columns(table).get(column)
        if col is None or getattr(col["type"], "timezone", False):
            continue  # fehlt oder ist schon timestamptz
        # USING: sagt PostgreSQL, wie die alten Werte zu interpretieren sind.
        # sa.text + bindparam wäre hier nicht möglich (DDL), daher Whitelist-Werte
        # aus der Konstante oben – keine Benutzereingaben.
        op.execute(
            f'ALTER TABLE "{table}" ALTER COLUMN "{column}" TYPE TIMESTAMP WITH TIME ZONE '
            f"USING \"{column}\" AT TIME ZONE '{source_tz}'"
        )

    # 4) Indizes --------------------------------------------------------------------------
    for name, table, cols in INDEXES:
        if not _has_index(table, name):
            op.create_index(name, table, cols, unique=False)

    # 5) RSVP-Duplikate entfernen (höchste id = neuester Eintrag bleibt) + UNIQUE -------
    if not _has_unique("event_rsvps", RSVP_UNIQUE):
        op.execute(
            "DELETE FROM event_rsvps a USING event_rsvps b "
            "WHERE a.event_id = b.event_id AND a.user_id = b.user_id AND a.id < b.id"
        )
        op.create_unique_constraint(RSVP_UNIQUE, "event_rsvps", ["event_id", "user_id"])


# ----------------------------------------------------------------------------- Downgrade
def downgrade() -> None:
    """Macht Indizes, Constraint und timestamptz rückgängig.

    Die in Schritt 1/2 ergänzten Tabellen/Spalten bleiben absichtlich erhalten: Sie
    könnten schon VOR dieser Migration existiert haben (siehe Kopfkommentar), und ein
    Downgrade soll keine Kundendaten löschen.
    """
    if _has_unique("event_rsvps", RSVP_UNIQUE):
        op.drop_constraint(RSVP_UNIQUE, "event_rsvps", type_="unique")

    for name, table, _cols in reversed(INDEXES):
        if _has_index(table, name):
            op.drop_index(name, table_name=table)

    for table, column, source_tz in TIMESTAMP_COLUMNS:
        col = _columns(table).get(column)
        if col is None or not getattr(col["type"], "timezone", False):
            continue
        op.execute(
            f'ALTER TABLE "{table}" ALTER COLUMN "{column}" TYPE TIMESTAMP WITHOUT TIME ZONE '
            f"USING \"{column}\" AT TIME ZONE '{source_tz}'"
        )
