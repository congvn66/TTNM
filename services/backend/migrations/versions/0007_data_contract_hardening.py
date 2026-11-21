"""Align unresolved evidence states and extraction provenance metadata.

The v2 evidence contract distinguishes a missing value from a value that could
not be read or mapped unambiguously.  The original baseline collapsed these
states in PostgreSQL, which made a valid adapter payload impossible to persist.
This migration is additive for existing rows and keeps legacy provider v1
payloads compatible at the application boundary.
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text


revision = "0007_data_contract_hardening"
down_revision = "0006_project_session_library"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table, value_column in (("extracted_evidences", "raw_value"), ("evidence_revisions", "numeric_value")):
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {table}_data_status_check")
        op.execute(
            f"""ALTER TABLE {table} ADD CONSTRAINT {table}_data_status_check
            CHECK (data_status IN ('valid','missing','unreadable','ambiguous','error'))"""
        )
        op.execute(
            f"""ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {table}_value_shape_check"""
        )
        if table == "extracted_evidences":
            op.execute(
                """ALTER TABLE extracted_evidences ADD CONSTRAINT extracted_evidences_value_shape_check
                CHECK (
                  (data_status='valid' AND value_kind='number' AND raw_value IS NOT NULL AND raw_text IS NULL)
                  OR (data_status='valid' AND value_kind='text' AND raw_text IS NOT NULL AND raw_value IS NULL)
                  OR (data_status IN ('missing','unreadable','ambiguous','error') AND raw_value IS NULL AND raw_text IS NULL)
                )"""
            )
        else:
            op.execute(
                """ALTER TABLE evidence_revisions ADD CONSTRAINT evidence_revisions_value_shape_check
                CHECK (
                  (data_status='valid' AND value_kind='number' AND numeric_value IS NOT NULL AND text_value IS NULL)
                  OR (data_status='valid' AND value_kind='text' AND text_value IS NOT NULL AND numeric_value IS NULL)
                  OR (data_status IN ('missing','unreadable','ambiguous','error') AND numeric_value IS NULL AND text_value IS NULL)
                )"""
            )

    op.execute("ALTER TABLE extraction_runs ADD COLUMN IF NOT EXISTS contract_name text")
    op.execute("ALTER TABLE extraction_runs ADD COLUMN IF NOT EXISTS contract_version integer")
    op.execute("ALTER TABLE extraction_runs ADD COLUMN IF NOT EXISTS scope text")
    op.execute("ALTER TABLE extraction_runs ADD COLUMN IF NOT EXISTS trigger jsonb")
    op.execute("ALTER TABLE extraction_runs ADD COLUMN IF NOT EXISTS input_sha256 text")
    op.execute("ALTER TABLE extraction_runs ADD COLUMN IF NOT EXISTS tool_meta jsonb NOT NULL DEFAULT '{}'::jsonb")
    op.execute(
        """UPDATE extraction_runs
              SET contract_name=COALESCE(contract_name,'document-evidence'),
                  contract_version=COALESCE(contract_version,1),
                  scope=COALESCE(scope,'base_document')
            WHERE contract_name IS NULL OR contract_version IS NULL OR scope IS NULL"""
    )
    op.execute("ALTER TABLE extraction_runs ALTER COLUMN contract_name SET NOT NULL")
    op.execute("ALTER TABLE extraction_runs ALTER COLUMN contract_version SET NOT NULL")
    op.execute("ALTER TABLE extraction_runs ALTER COLUMN scope SET NOT NULL")
    op.execute("ALTER TABLE extraction_runs ALTER COLUMN contract_version SET DEFAULT 1")
    op.execute("ALTER TABLE extraction_runs ALTER COLUMN scope SET DEFAULT 'base_document'")
    op.execute(
        """ALTER TABLE extraction_runs ADD CONSTRAINT extraction_runs_contract_version_ck
           CHECK (contract_version > 0)"""
    )
    op.execute(
        """ALTER TABLE extraction_runs ADD CONSTRAINT extraction_runs_scope_trigger_ck
           CHECK ((scope='base_document' AND trigger IS NULL)
              OR (scope='on_demand_chart' AND jsonb_typeof(trigger)='object'))"""
    )
    op.execute(
        """ALTER TABLE extraction_runs ADD CONSTRAINT extraction_runs_scope_ck
           CHECK (scope IN ('base_document','on_demand_chart'))"""
    )
    op.execute(
        """CREATE INDEX IF NOT EXISTS extraction_runs_version_scope_idx
           ON extraction_runs (document_version_id, scope, created_at DESC)"""
    )
    op.execute(
        """CREATE UNIQUE INDEX IF NOT EXISTS extraction_runs_chart_dedup_uq
           ON extraction_runs (document_version_id, scope, input_sha256)
           WHERE scope='on_demand_chart' AND status='completed' AND input_sha256 IS NOT NULL"""
    )


def downgrade() -> None:
    rows = op.get_bind().execute(
        text(
            """SELECT EXISTS (
                 SELECT 1 FROM extracted_evidences
                  WHERE data_status IN ('unreadable','ambiguous')
               ) OR EXISTS (
                 SELECT 1 FROM evidence_revisions
                  WHERE data_status IN ('unreadable','ambiguous')
               ) AS has_unresolved"""
        )
    ).scalar_one()
    if rows:
        raise RuntimeError("Cannot downgrade data contract while unresolved evidence rows exist")
    op.execute("DROP INDEX IF EXISTS extraction_runs_version_scope_idx")
    op.execute("DROP INDEX IF EXISTS extraction_runs_chart_dedup_uq")
    op.execute("ALTER TABLE extraction_runs DROP CONSTRAINT IF EXISTS extraction_runs_scope_trigger_ck")
    op.execute("ALTER TABLE extraction_runs DROP CONSTRAINT IF EXISTS extraction_runs_scope_ck")
    op.execute("ALTER TABLE extraction_runs DROP CONSTRAINT IF EXISTS extraction_runs_contract_version_ck")
    op.execute("ALTER TABLE extraction_runs DROP COLUMN IF EXISTS tool_meta")
    op.execute("ALTER TABLE extraction_runs DROP COLUMN IF EXISTS input_sha256")
    op.execute("ALTER TABLE extraction_runs DROP COLUMN IF EXISTS trigger")
    op.execute("ALTER TABLE extraction_runs DROP COLUMN IF EXISTS scope")
    op.execute("ALTER TABLE extraction_runs DROP COLUMN IF EXISTS contract_version")
    op.execute("ALTER TABLE extraction_runs DROP COLUMN IF EXISTS contract_name")
    for table in ("extracted_evidences", "evidence_revisions"):
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {table}_value_shape_check")
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {table}_data_status_check")
        op.execute(
            f"""ALTER TABLE {table} ADD CONSTRAINT {table}_data_status_check
            CHECK (data_status IN ('valid','missing','error'))"""
        )
