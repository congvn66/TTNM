"""Add owner-scoped folders and project document presentation metadata."""

from __future__ import annotations

from alembic import op


revision = "0003_library_folders"
down_revision = "0002_chat_documents"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """CREATE TABLE folders (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            owner_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
            project_id uuid NOT NULL,
            parent_id uuid,
            name text NOT NULL CHECK (length(btrim(name)) > 0),
            normalized_name text NOT NULL,
            sort_order numeric NOT NULL DEFAULT 0,
            version bigint NOT NULL DEFAULT 1 CHECK (version > 0),
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            deleted_at timestamptz,
            UNIQUE (id, project_id, owner_id),
            FOREIGN KEY (project_id, owner_id) REFERENCES projects(id, owner_id) ON DELETE CASCADE,
            FOREIGN KEY (parent_id, project_id, owner_id) REFERENCES folders(id, project_id, owner_id) ON DELETE RESTRICT
        )"""
    )
    op.execute("CREATE UNIQUE INDEX folders_sibling_name_uk ON folders (project_id, COALESCE(parent_id, '00000000-0000-0000-0000-000000000000'::uuid), normalized_name) WHERE deleted_at IS NULL")
    op.execute("CREATE INDEX folders_project_parent_idx ON folders (project_id, parent_id, sort_order, name) WHERE deleted_at IS NULL")
    op.execute("ALTER TABLE project_documents ADD COLUMN folder_id uuid, ADD COLUMN display_name text, ADD COLUMN sort_order numeric NOT NULL DEFAULT 0, ADD COLUMN archived_at timestamptz, ADD COLUMN version bigint NOT NULL DEFAULT 1")
    op.execute("ALTER TABLE project_documents ADD CONSTRAINT project_documents_folder_fk FOREIGN KEY (folder_id, project_id, owner_id) REFERENCES folders(id, project_id, owner_id) ON DELETE RESTRICT")
    op.execute("UPDATE project_documents SET display_name = (SELECT title FROM documents WHERE documents.id=project_documents.document_id) WHERE display_name IS NULL")
    op.execute("ALTER TABLE project_documents ALTER COLUMN display_name SET NOT NULL")


def downgrade() -> None:
    op.execute("ALTER TABLE project_documents DROP CONSTRAINT project_documents_folder_fk")
    op.execute("ALTER TABLE project_documents DROP COLUMN folder_id, DROP COLUMN display_name, DROP COLUMN sort_order, DROP COLUMN archived_at, DROP COLUMN version")
    op.execute("DROP TABLE folders")
