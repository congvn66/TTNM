"""Add the remaining auth/session and user preference fields."""

from alembic import op


revision = "0004_auth_preferences"
down_revision = "0003_library_folders"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE auth_sessions ADD COLUMN IF NOT EXISTS user_agent text")
    op.execute("ALTER TABLE auth_sessions ADD COLUMN IF NOT EXISTS ip_hash text")
    op.execute(
        """CREATE TABLE IF NOT EXISTS user_preferences (
            user_id uuid PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
            theme text NOT NULL DEFAULT 'system' CHECK (theme IN ('light','dark','system')),
            locale text NOT NULL DEFAULT 'vi-VN',
            default_answer_style text NOT NULL DEFAULT 'grounded',
            version bigint NOT NULL DEFAULT 1 CHECK (version > 0),
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        )"""
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS user_preferences")
    op.execute("ALTER TABLE auth_sessions DROP COLUMN IF EXISTS ip_hash")
    op.execute("ALTER TABLE auth_sessions DROP COLUMN IF EXISTS user_agent")
