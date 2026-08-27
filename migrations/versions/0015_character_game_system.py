"""Per-character game system + Dungeon Crawler Carl sheet fields.

- tblCharacters.game_system ('dnd5e' | 'dcc'): which sheet layout and stat
  table the character uses. Existing characters stay D&D 5e.
- tblCharacters.dcc_json: the DCC-only sheet bag (Enhanced stats, DR,
  Move/Step/Size, Popularity, AI Favor, crawler number, pronouns, past
  trauma / loose ends / regrets, unspent Stat points). One JSON column so
  Backup → Restore/Merge carries it verbatim.
- tblCharacterSkills.category / stat: DCC skills are ranked and belong to a
  category (Attack/Spell/Utility/Passive) and a Stat; Rank lives in `bonus`.
- tblCharacterInventory.hotlist: 1 = on the crawler's 10-slot Hotlist.

Revision ID: 0015_character_game_system
Revises: 0014_session_game_system
Create Date: 2026-08-26
"""
from alembic import op

revision = '0015_character_game_system'
down_revision = '0014_session_game_system'
branch_labels = None
depends_on = None

_ADDS = [
    ('tblCharacters', 'game_system', "TEXT NOT NULL DEFAULT 'dnd5e'"),
    ('tblCharacters', 'dcc_json', "TEXT NOT NULL DEFAULT '{}'"),
    ('tblCharacterSkills', 'category', "TEXT NOT NULL DEFAULT ''"),
    ('tblCharacterSkills', 'stat', "TEXT NOT NULL DEFAULT ''"),
    ('tblCharacterInventory', 'hotlist', "INTEGER NOT NULL DEFAULT 0"),
]


def upgrade():
    bind = op.get_bind()
    have = {r[0].lower(): r[0] for r in bind.exec_driver_sql(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    for table, col, ddl in _ADDS:
        real = have.get(table.lower())
        if not real:
            continue
        cols = {r[1] for r in bind.exec_driver_sql(f'PRAGMA table_info("{real}")')}
        if col not in cols:
            bind.exec_driver_sql(f'ALTER TABLE "{real}" ADD COLUMN {col} {ddl}')


def downgrade():
    pass
