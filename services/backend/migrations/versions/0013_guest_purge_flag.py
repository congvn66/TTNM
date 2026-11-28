"""Let guest cleanup delete immutable rows, and keep its file list across retries.

Revision rows (evidence and answer revisions, answer inputs and scopes) and
the rows of a completed reading (source regions, extracted evidences) are
immutable by trigger. A guest's rows must still go when the guest expires,
and Supabase gives no superuser to bypass triggers. So the trigger functions
let a change through only in a transaction that ran
``SET LOCAL app.guest_purge = 'on'``: a DELETE, or an UPDATE of a revision
that changes nothing but its author (sign-in moves a guest's edits to the
account). Every other change is refused as before.

users.guest_cleanup_files holds a purged guest's file list between the row
delete and the file delete, so a failed file delete is retried.
"""

from __future__ import annotations

from alembic import op


revision = "0013_guest_purge_flag"
down_revision = "0012_guest_limits_cleanup"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS guest_cleanup_files jsonb")
    op.execute(
        """
        CREATE OR REPLACE FUNCTION app_deny_revision_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF current_setting('app.guest_purge', true) = 'on' THEN
                IF TG_OP = 'DELETE' THEN
                    RETURN OLD;
                END IF;
                IF (to_jsonb(NEW) - 'created_by') = (to_jsonb(OLD) - 'created_by') THEN
                    RETURN NEW;
                END IF;
            END IF;
            RAISE EXCEPTION 'revision_rows_are_immutable';
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION app_guard_extraction_payload()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            run_id uuid;
            run_status text;
        BEGIN
            IF TG_OP = 'DELETE' AND current_setting('app.guest_purge', true) = 'on' THEN
                RETURN OLD;
            END IF;
            run_id := CASE WHEN TG_OP = 'DELETE' THEN OLD.extraction_run_id ELSE NEW.extraction_run_id END;
            SELECT status INTO run_status FROM extraction_runs WHERE id = run_id;
            IF run_status = 'completed' THEN
                RAISE EXCEPTION 'completed_extraction_is_immutable';
            END IF;
            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION app_deny_revision_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION 'revision_rows_are_immutable';
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION app_guard_extraction_payload()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            run_id uuid;
            run_status text;
        BEGIN
            run_id := CASE WHEN TG_OP = 'DELETE' THEN OLD.extraction_run_id ELSE NEW.extraction_run_id END;
            SELECT status INTO run_status FROM extraction_runs WHERE id = run_id;
            IF run_status = 'completed' THEN
                RAISE EXCEPTION 'completed_extraction_is_immutable';
            END IF;
            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS guest_cleanup_files")
