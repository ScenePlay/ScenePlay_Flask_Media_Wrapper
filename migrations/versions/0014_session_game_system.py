"""Per-session game system for the dice roller.

tblSessions gains `game_system` ('dnd5e' | 'dcc', see dice_systems.py) and
`system_settings` (JSON, e.g. {"floor": 3} for Dungeon Crawler Carl). The DM
picks these on the session page; every roller follows the ACTIVE session.
Existing rows default to D&D 5e so nothing changes for current campaigns.

Revision ID: 0014_session_game_system
Revises: 0013_prune_orphan_scene_links_again
Create Date: 2026-08-26
"""
from alembic import op

revision = '0014_session_game_system'
down_revision = '0013_prune_orphan_scene_links_again'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    have = {r[0].lower() for r in bind.exec_driver_sql(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    if 'tblsessions' not in have:
        return
    cols = {r[1] for r in bind.exec_driver_sql("PRAGMA table_info(tblSessions)")}
    if 'game_system' not in cols:
        bind.exec_driver_sql(
            "ALTER TABLE tblSessions ADD COLUMN game_system TEXT NOT NULL DEFAULT 'dnd5e'")
    if 'system_settings' not in cols:
        bind.exec_driver_sql(
            "ALTER TABLE tblSessions ADD COLUMN system_settings TEXT NOT NULL DEFAULT '{}'")


def downgrade():
    pass
