"""Guest limits and cleanup: indexes for the counts, and a failure count per guest.

The guest limits count recent guest sessions per address, recent guests and
recent guest uploads; these indexes keep those counts cheap. Cleanup records
each failed purge on the user row and stops retrying a guest after a few
failures. Plain CREATE INDEX blocks writes to the table while it builds: run
this with the API and workers stopped.
"""

from __future__ import annotations

from alembic import op


revision = "0012_guest_limits_cleanup"
down_revision = "0011_guest_users"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS guest_cleanup_attempts integer NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS guest_cleanup_failed_at timestamptz")
    op.execute("CREATE INDEX IF NOT EXISTS auth_sessions_ip_created_idx ON auth_sessions (ip_hash, created_at)")
    op.execute("CREATE INDEX IF NOT EXISTS users_guest_created_idx ON users (created_at) WHERE is_guest")
    op.execute("CREATE INDEX IF NOT EXISTS users_guest_closed_idx ON users (deleted_at) WHERE is_guest AND deleted_at IS NOT NULL")
    op.execute("CREATE INDEX IF NOT EXISTS documents_owner_created_idx ON documents (owner_id, created_at)")
    op.execute("CREATE INDEX IF NOT EXISTS evidence_revisions_created_by_idx ON evidence_revisions (created_by) WHERE created_by IS NOT NULL")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS evidence_revisions_created_by_idx")
    op.execute("DROP INDEX IF EXISTS documents_owner_created_idx")
    op.execute("DROP INDEX IF EXISTS users_guest_closed_idx")
    op.execute("DROP INDEX IF EXISTS users_guest_created_idx")
    op.execute("DROP INDEX IF EXISTS auth_sessions_ip_created_idx")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS guest_cleanup_failed_at")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS guest_cleanup_attempts")
