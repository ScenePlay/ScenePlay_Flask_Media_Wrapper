"""3D texture library: user-added textures (AI paste-backs, uploads).

Built-in textures are repo files (static/textures/builtin/); this table only
holds what authors add. `name` is the slug floorplan JSON references.

Additive table only — guarded so re-runs are safe.

Revision ID: 0008_texture_library
Revises: 0007_obs_video_feed
Create Date: 2026-08-19
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = '0008_texture_library'
down_revision = '0007_obs_video_feed'
branch_labels = None
depends_on = None


def _tables(bind):
    return [r[0] for r in bind.exec_driver_sql(
        "SELECT name FROM sqlite_master WHERE type='table'")]


def upgrade():
    bind = op.get_bind()
    if 'tblTextures' in _tables(bind):
        return
    bind.exec_driver_sql('''
        CREATE TABLE tblTextures (
            texture_id INTEGER PRIMARY KEY,
            name       TEXT NOT NULL UNIQUE,
            category   TEXT NOT NULL DEFAULT 'other',
            source     TEXT NOT NULL DEFAULT 'upload',
            filename   TEXT NOT NULL,
            tile_ft    FLOAT NOT NULL DEFAULT 5.0,
            created_at TEXT NOT NULL
        )
    ''')


def downgrade():
    bind = op.get_bind()
    if 'tblTextures' in _tables(bind):
        bind.exec_driver_sql('DROP TABLE tblTextures')
