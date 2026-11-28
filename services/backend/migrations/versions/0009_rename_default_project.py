"""Name every account's default project "Báo cáo của tôi".

Migration 0006 created it as "Workspace cá nhân", and its repair step for
mojibake names wrote "Workspace á nhân" (the "c" was left out). Both become
"Báo cáo của tôi". An account that already has a project of that name keeps
its old default project as it is, since project names are unique per owner.
"""

from __future__ import annotations

from alembic import op


revision = "0009_rename_default_project"
down_revision = "0008_drop_legacy_evidence_checks"
branch_labels = None
depends_on = None

NEW_NAME = "Báo cáo của tôi"
OLD_NAMES = ("Workspace cá nhân", "Workspace " + chr(225) + " nh" + chr(226) + "n")


def upgrade() -> None:
    for old in OLD_NAMES:
        op.execute(
            f"""UPDATE projects
                   SET name = '{NEW_NAME}', updated_at = now()
                 WHERE name = '{old}'
                   AND deleted_at IS NULL
                   AND NOT EXISTS (
                         SELECT 1 FROM projects other
                          WHERE other.owner_id = projects.owner_id
                            AND other.name = '{NEW_NAME}'
                            AND other.deleted_at IS NULL
                   )"""
        )


def downgrade() -> None:
    op.execute(f"UPDATE projects SET name = '{OLD_NAMES[0]}' WHERE name = '{NEW_NAME}' AND deleted_at IS NULL")
