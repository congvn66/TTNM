"""Guests: people who use SourceLens before they make an account.

A guest is an ordinary users row with is_guest = true and an expiry, so every
table that belongs to a user works for guests unchanged. Signing up turns the
row into a normal account in place. Signing in to an existing account moves
the guest's reports to that account: the owner_id foreign keys that pair a
row's id with its owner become DEFERRABLE, so one transaction can change the
owner of a project and its chats, folders and documents together and have the
pairs checked once, at commit.
"""

from __future__ import annotations

from alembic import op


revision = "0010_guest_users"
down_revision = "0009_optional_edit_reason"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_guest boolean NOT NULL DEFAULT false")
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS guest_expires_at timestamptz")
    op.execute("CREATE INDEX IF NOT EXISTS users_guest_expiry_idx ON users (guest_expires_at) WHERE is_guest AND deleted_at IS NULL")
    op.execute(
        """
        DO $$
        DECLARE item record;
        BEGIN
            FOR item IN
                SELECT conrelid::regclass AS tab, conname FROM pg_constraint
                WHERE contype = 'f' AND connamespace = current_schema()::regnamespace
                  AND array_length(conkey, 1) > 1 AND pg_get_constraintdef(oid) ILIKE '%owner_id%'
            LOOP
                EXECUTE format('ALTER TABLE %s ALTER CONSTRAINT %I DEFERRABLE INITIALLY IMMEDIATE', item.tab, item.conname);
            END LOOP;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS users_guest_expiry_idx")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS guest_expires_at")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS is_guest")
