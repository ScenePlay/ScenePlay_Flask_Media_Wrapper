"""Data fix: drop scene links (tblMusicScene / tblVideoScene) whose scene no
longer exists — including links to the All Stop pseudo-scene (-1).

Songs linked to scene -1 were re-queued by every All Stop: the button kills
the queue, then "activates" pseudo-scene -1, which loaded that scene's
links like any other. Rows like these came from table edits against a
deleted or never-real scene id. Idempotent; safe on a fresh install.

Revision ID: 0012_prune_orphan_scene_links
Revises: 0011_media_facets
Create Date: 2026-08-26
"""
from alembic import op

revision = '0012_prune_orphan_scene_links'
down_revision = '0011_media_facets'
branch_labels = None
depends_on = None


def _tables(bind):
    # lower-cased: sqlite_master keeps whatever case the table was created
    # with, and older databases were created by hand with different casing
    return {r[0].lower() for r in bind.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table'")}


def upgrade():
    bind = op.get_bind()
    have = _tables(bind)
    if 'tblscenes' not in have:
        return
    for link in ('tblMusicScene', 'tblVideoScene'):
        if link.lower() in have:
            bind.exec_driver_sql(
                f"DELETE FROM {link} WHERE scene_ID IS NULL OR scene_ID <= 0 "
                f"OR scene_ID NOT IN (SELECT scene_ID FROM tblScenes)")


def downgrade():
    pass
