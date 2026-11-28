"""Make the Library rows of moved and renamed reports match their chats.

Moving a chat to another project used to add its reports to the new project
and leave them in the old one too, so the old project listed them and could
never be deleted. A report row is removed from a project when a live chat
holds the report but no live chat of that project does. A report that no
live chat holds keeps its rows.

Renaming a report changed its file name but not its Library name. The
Library name is set from the newest file name again; no screen edits the
Library name on its own.
"""

from __future__ import annotations

from alembic import op


revision = "0014_library_links_follow_chats"
down_revision = "0013_guest_purge_flag"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """DELETE FROM project_documents pd
            WHERE EXISTS (SELECT 1 FROM chats c JOIN chat_documents cd ON cd.chat_id=c.id
                            JOIN document_versions dv ON dv.id=cd.document_version_id
                           WHERE c.deleted_at IS NULL AND dv.document_id=pd.document_id)
              AND NOT EXISTS (SELECT 1 FROM chats c JOIN chat_documents cd ON cd.chat_id=c.id
                                JOIN document_versions dv ON dv.id=cd.document_version_id
                               WHERE c.deleted_at IS NULL AND c.project_id=pd.project_id AND dv.document_id=pd.document_id)"""
    )
    op.execute(
        """UPDATE project_documents pd
              SET display_name=latest.file_name, version=pd.version+1
             FROM (SELECT DISTINCT ON (document_id) document_id, file_name
                     FROM document_versions ORDER BY document_id, version_no DESC) latest
            WHERE latest.document_id=pd.document_id AND pd.display_name IS DISTINCT FROM latest.file_name"""
    )


def downgrade() -> None:
    # The removed rows were wrong; there is nothing to put back.
    pass
