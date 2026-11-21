"""Backfill the project/session boundary used by the document library.

Chats are the user-facing analysis sessions.  Projects are their durable
library container; a session belongs to exactly one owner project and each
document referenced by that session is materialised in ``project_documents``
so folders can organise it without changing chat semantics.
"""

from alembic import op


revision = "0006_project_session_library"
down_revision = "0005_processing_answer_status"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Every existing owner gets one stable library container.  The partial
    # unique index below keeps the backfill idempotent for a retry.
    op.execute(
        """CREATE UNIQUE INDEX IF NOT EXISTS projects_owner_default_name_uk
           ON projects (owner_id, name) WHERE deleted_at IS NULL"""
    )
    op.execute(
        """INSERT INTO projects (owner_id, name)
           SELECT u.id, 'Workspace cá nhân'
             FROM users u
            WHERE u.deleted_at IS NULL
              AND NOT EXISTS (
                SELECT 1 FROM projects p
                 WHERE p.owner_id=u.id AND p.name='Workspace cá nhân' AND p.deleted_at IS NULL
              )"""
    )
    op.execute(
        """UPDATE chats c
              SET project_id = p.id
             FROM projects p
            WHERE c.project_id IS NULL
              AND p.owner_id=c.owner_id
              AND p.name='Workspace cá nhân'
              AND p.deleted_at IS NULL"""
    )
    # Repair databases created by the earlier mojibake-labelled migration
    # without touching an explicitly named user project.
    op.execute(
        """UPDATE projects
              SET name = 'Workspace ' || chr(225) || ' nh' || chr(226) || 'n'
            WHERE name = convert_from(decode('576f726b73706163652063c383c2a1206e68c383c2a26e', 'hex'), 'UTF8')
              AND NOT EXISTS (
                    SELECT 1 FROM projects p2
                     WHERE p2.owner_id = projects.owner_id
                       AND p2.name = 'Workspace ' || chr(225) || ' nh' || chr(226) || 'n'
                       AND p2.deleted_at IS NULL
              )"""
    )
    op.execute("CREATE INDEX IF NOT EXISTS chats_project_idx ON chats (owner_id, project_id, updated_at DESC) WHERE deleted_at IS NULL")
    op.execute(
        """INSERT INTO project_documents (owner_id, project_id, document_id, display_name)
           SELECT DISTINCT c.owner_id, c.project_id, dv.document_id,
                           COALESCE(NULLIF(btrim(d.title), ''), 'Tài liệu chưa đặt tên')
             FROM chats c
             JOIN chat_documents cd ON cd.chat_id=c.id
             JOIN document_versions dv ON dv.id=cd.document_version_id
             JOIN documents d ON d.id=dv.document_id AND d.owner_id=c.owner_id
            WHERE c.project_id IS NOT NULL
           ON CONFLICT (project_id, document_id) DO NOTHING"""
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS chats_project_idx")
    op.execute("DROP INDEX IF EXISTS projects_owner_default_name_uk")
