"""Add sort_order to tblBattleMapNotes for DM-defined note ordering.

The guard also covers fresh databases: there db.create_all() builds the table
with sort_order already present before this migration runs, so the PRAGMA
check sees the column and skips the ALTER.

Revision ID: 0004_map_note_sort
Revises: 0003_dn_last_error
Create Date: 2026-07-22
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = '0004_map_note_sort'
down_revision = '0003_dn_last_error'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    cols = [r[1] for r in bind.exec_driver_sql('PRAGMA table_info("tblBattleMapNotes")')]
    if cols and 'sort_order' not in cols:
        bind.exec_driver_sql(
            'ALTER TABLE tblBattleMapNotes ADD COLUMN sort_order INTEGER DEFAULT 0')


def downgrade():
    # SQLite can't drop columns portably; harmless to leave in place.
    pass
