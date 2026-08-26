"""tblMediaMetadata facets: artist (+ how it was derived) and the playlist a
download came from.

artist / artist_source are filled by meta_que for new downloads (exact or
channel-confirmed derivations only) and by the DM on Utilities → Artists;
origin_playlist / origin_playlist_title are stamped by playlist_que when a
playlist is expanded. All default '' so nothing else changes shape.

Guarded: a database that already has the columns passes straight through.

Revision ID: 0011_media_facets
Revises: 0010_led_pattern_params
Create Date: 2026-08-26
"""
from alembic import op

revision = '0011_media_facets'
down_revision = '0010_led_pattern_params'
branch_labels = None
depends_on = None

COLUMNS = (('artist', "TEXT DEFAULT ''"), ('artist_source', "TEXT DEFAULT ''"),
           ('origin_playlist', "TEXT DEFAULT ''"), ('origin_playlist_title', "TEXT DEFAULT ''"))


def _columns(bind, table):
    return [r[1] for r in bind.exec_driver_sql(f'PRAGMA table_info("{table}")')]


def upgrade():
    bind = op.get_bind()
    cols = _columns(bind, 'tblMediaMetadata')
    if not cols:
        return          # fresh install: create_table already made the full shape
    for name, decl in COLUMNS:
        if name not in cols:
            bind.exec_driver_sql(f'ALTER TABLE tblMediaMetadata ADD COLUMN {name} {decl}')


def downgrade():
    pass    # SQLite cannot drop columns portably; the columns are harmless
