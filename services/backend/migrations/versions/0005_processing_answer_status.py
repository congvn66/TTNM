"""Allow an answer revision to represent a durable processing placeholder."""

from alembic import op


revision = "0005_processing_answer_status"
down_revision = "0004_auth_preferences"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE answer_revisions DROP CONSTRAINT IF EXISTS answer_revisions_answer_status_check")
    op.execute(
        """ALTER TABLE answer_revisions ADD CONSTRAINT answer_revisions_answer_status_check
        CHECK (answer_status IN ('processing','answered','needs_clarification','insufficient_data','source_conflict','processing_error'))"""
    )


def downgrade() -> None:
    op.execute("UPDATE answer_revisions SET answer_status='processing_error' WHERE answer_status='processing'")
    op.execute("ALTER TABLE answer_revisions DROP CONSTRAINT IF EXISTS answer_revisions_answer_status_check")
    op.execute(
        """ALTER TABLE answer_revisions ADD CONSTRAINT answer_revisions_answer_status_check
        CHECK (answer_status IN ('answered','needs_clarification','insufficient_data','source_conflict','processing_error'))"""
    )
