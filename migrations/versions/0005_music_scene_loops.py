"""Add loops to tblMusicScene — per-scene music repeat count.

Mirrors tblVideoScene.loops: mpv plays the file (loops + 1) times via
--loop-file, so a short mood track can repeat inside a scene. 0 (the
default) keeps the old play-once behavior.

The guard also covers fresh databases: there create_table() builds the
table with loops already present before this migration runs, so the
PRAGMA check sees the column and skips the ALTER.

Revision ID: 0005_music_scene_loops
Revises: 0004_map_note_sort
Create Date: 2026-07-23
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = '0005_music_scene_loops'
down_revision = '0004_map_note_sort'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    cols = [r[1] for r in bind.exec_driver_sql('PRAGMA table_info("tblMusicScene")')]
    if cols and 'loops' not in cols:
        bind.exec_driver_sql(
            'ALTER TABLE tblMusicScene ADD COLUMN loops INT DEFAULT 0')


def downgrade():
    # SQLite can't drop columns portably; harmless to leave in place.
    pass
