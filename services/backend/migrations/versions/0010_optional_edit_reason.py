"""Let a number be corrected without a written reason.

The baseline schema has an unnamed check that every edit, mark_error and
restore revision carries a non-empty reason (Postgres named it
evidence_revisions_check1). The reader now makes the note optional, so that
check rejected every edit saved without one. The check is found by what it
checks, not by its generated name.
"""

from __future__ import annotations

from alembic import op


revision = "0010_optional_edit_reason"
down_revision = "0009_rename_default_project"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        DECLARE item record;
        BEGIN
            FOR item IN
                SELECT conname FROM pg_constraint
                WHERE conrelid = 'evidence_revisions'::regclass AND contype = 'c'
                  AND pg_get_constraintdef(oid) ILIKE '%btrim(COALESCE(reason%'
            LOOP
                EXECUTE format('ALTER TABLE evidence_revisions DROP CONSTRAINT %I', item.conname);
            END LOOP;
        END $$;
        """
    )


def downgrade() -> None:
    # Rows saved without a note would violate the old check; it is not restored.
    pass
