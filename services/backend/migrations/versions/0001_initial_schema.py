"""Create the reviewed 23-table PostgreSQL baseline.

The design baseline is intentionally kept in ``doc/initial-schema.sql`` so
design review, Docker bootstrap and Alembic use the same SQL. Later revisions
must be explicit migrations and must not edit this file.
"""

from __future__ import annotations

from pathlib import Path

from alembic import op


revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    schema_file = Path(__file__).resolve().parents[4] / "doc" / "initial-schema.sql"
    op.execute(schema_file.read_text(encoding="utf-8"))


def downgrade() -> None:
    # This migration is only downgraded on a disposable migration-test DB.
    # Never run it against a shared database without an explicit backup.
    op.execute("DROP SCHEMA public CASCADE")
    op.execute("CREATE SCHEMA public")
