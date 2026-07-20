"""Add dnLastError to both media tables.

A failed download (dnLoadStatus 4) previously left NO per-row diagnostics —
the only trace was instance/ytdlp_last.log, which the next download overwrites.
yt_que.YT_Exec now stores the yt-dlp error text here on failure (and clears it
on success) so failures can be diagnosed from the media tables.

Revision ID: 0003_dn_last_error
Revises: 0002_slim_raw_json
Create Date: 2026-07-20
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = '0003_dn_last_error'
down_revision = '0002_slim_raw_json'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    for table in ('tblMusic', 'tblVideoMedia'):
        cols = [r[1] for r in bind.exec_driver_sql(f'PRAGMA table_info("{table}")')]
        if cols and 'dnLastError' not in cols:
            bind.exec_driver_sql(f'ALTER TABLE {table} ADD COLUMN dnLastError TEXT')


def downgrade():
    # SQLite can't drop columns portably; harmless to leave in place.
    pass
