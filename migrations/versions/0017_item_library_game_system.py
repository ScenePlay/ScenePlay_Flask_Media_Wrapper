"""Game-system tag on the item libraries.

tblWeaponsLibrary / tblArmorLibrary / tblEquipmentLibrary /
tblMagicItemsLibrary gain `game_system` ('dnd5e' default — every synced SRD
row and existing homebrew row keeps working as D&D 5e). The built-in Dungeon
Crawler Carl items (dcc_library.py, seeded at boot: attack-skill weapons,
DR armor tiers, loot-box consumables and sample magical gear) use 'dcc', and
the sheet pickers / portal filter by the character's system — a crawler no
longer shops the SRD's gp-priced gear.

Revision ID: 0017_item_library_game_system
Revises: 0016_library_game_system
Create Date: 2026-08-27
"""
from alembic import op

revision = '0017_item_library_game_system'
down_revision = '0016_library_game_system'
branch_labels = None
depends_on = None

_TABLES = ('tblWeaponsLibrary', 'tblArmorLibrary', 'tblEquipmentLibrary', 'tblMagicItemsLibrary')


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
