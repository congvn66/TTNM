"""Remove baseline evidence checks superseded by the v2 data contract.

Migration 0007 added the explicit ``*_value_shape_check`` constraints, but
the baseline schema's unnamed checks remained in place.  Those legacy checks
only allowed ``missing``/``error`` unresolved rows and rejected legitimate
``ambiguous``/``unreadable`` evidence emitted by Docling/table extraction.
That made the worker retry extraction forever even though the artifact itself
was valid.
"""

from __future__ import annotations

from alembic import op


revision = "0008_drop_legacy_evidence_checks"
down_revision = "0007_data_contract_hardening"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE extracted_evidences DROP CONSTRAINT IF EXISTS extracted_evidences_check")
    op.execute("ALTER TABLE evidence_revisions DROP CONSTRAINT IF EXISTS evidence_revisions_check")


def downgrade() -> None:
    # Do not restore the incompatible baseline checks.  The v2 value-shape
    # constraints from 0007 are the canonical contract and remain active.
    pass
