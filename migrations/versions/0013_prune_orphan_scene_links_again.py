"""Re-run the orphan scene-link prune.

0012's table check compared sqlite_master names case-sensitively; on
databases whose tables were created with different casing it returned
early, so the revision was stamped without deleting anything. This
revision repeats the (now case-insensitive) prune so those databases catch
up. Idempotent; a no-op where 0012 already worked.

Revision ID: 0013_prune_orphan_scene_links_again
Revises: 0012_prune_orphan_scene_links
Create Date: 2026-08-26
"""
from alembic import op

revision = '0013_prune_orphan_scene_links_again'
down_revision = '0012_prune_orphan_scene_links'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    have = {r[0].lower() for r in bind.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table'")}
    if 'tblscenes' not in have:
        return
    for link in ('tblMusicScene', 'tblVideoScene'):
        if link.lower() in have:
            bind.exec_driver_sql(
                f"DELETE FROM {link} WHERE scene_ID IS NULL OR scene_ID <= 0 "
                f"OR scene_ID NOT IN (SELECT scene_ID FROM tblScenes)")


def downgrade():
    pass
