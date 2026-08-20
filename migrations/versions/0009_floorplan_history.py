"""Floorplan history: last-N snapshots per map with a restore endpoint.

Additive table only — guarded so re-runs are safe.

Revision ID: 0009_floorplan_history
Revises: 0008_texture_library
Create Date: 2026-08-19
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = '0009_floorplan_history'
down_revision = '0008_texture_library'
branch_labels = None
depends_on = None


def _tables(bind):
    return [r[0] for r in bind.exec_driver_sql(
        "SELECT name FROM sqlite_master WHERE type='table'")]


def upgrade():
    bind = op.get_bind()
    if 'tblBattleMapFloorplanHistory' in _tables(bind):
        return
    bind.exec_driver_sql('''
        CREATE TABLE tblBattleMapFloorplanHistory (
            hist_id   INTEGER PRIMARY KEY,
            map_id    INTEGER NOT NULL,
            version   INTEGER NOT NULL,
            json_data TEXT NOT NULL,
            saved_at  TEXT NOT NULL
        )
    ''')


def downgrade():
    bind = op.get_bind()
    if 'tblBattleMapFloorplanHistory' in _tables(bind):
        bind.exec_driver_sql('DROP TABLE tblBattleMapFloorplanHistory')
