"""Keep uploaded documents visible while extraction is pending or failed."""

from __future__ import annotations

from alembic import op


revision = "0002_chat_documents"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """CREATE TABLE chat_documents (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            chat_id uuid NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
            document_version_id uuid NOT NULL REFERENCES document_versions(id) ON DELETE RESTRICT,
            status text NOT NULL CHECK (status IN ('queued','processing','ready','failed')),
            error_code text,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (chat_id, document_version_id)
        )"""
    )
    op.execute("CREATE INDEX chat_documents_chat_idx ON chat_documents (chat_id, updated_at DESC)")


def downgrade() -> None:
    op.execute("DROP TABLE chat_documents")

