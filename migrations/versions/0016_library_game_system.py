"""Game-system tag on the reference libraries.

tblSkillsLibrary / tblRacesLibrary / tblClassesLibrary gain `game_system`
('dnd5e' default — every synced SRD row and existing homebrew row keeps
working as D&D 5e). The built-in Dungeon Crawler Carl entries (dcc_library.py,
seeded at boot) use 'dcc', and the sheet pickers filter by the character's
system so a crawler never sees Dwarf/Wizard from the SRD and vice versa.

Revision ID: 0016_library_game_system
Revises: 0015_character_game_system
Create Date: 2026-08-26
"""
from alembic import op

revision = '0016_library_game_system'
down_revision = '0015_character_game_system'
branch_labels = None
depends_on = None

_TABLES = ('tblSkillsLibrary', 'tblRacesLibrary', 'tblClassesLibrary')


def upgrade():
    bind = op.get_bind()
    have = {r[0].lower(): r[0] for r in bind.exec_driver_sql(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    for table in _TABLES:
        real = have.get(table.lower())
        if not real:
            continue
        cols = {r[1] for r in bind.exec_driver_sql(f'PRAGMA table_info("{real}")')}
        if 'game_system' not in cols:
            bind.exec_driver_sql(
                f'ALTER TABLE "{real}" ADD COLUMN game_system TEXT NOT NULL DEFAULT \'dnd5e\'')


def downgrade():
    pass
