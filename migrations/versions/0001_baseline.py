"""Baseline: bring any pre-Alembic ScenePlay database up to the current schema.

Absorbs the ad-hoc "lightweight migration" blocks that used to live in app.py.
Tables themselves come from sql.create_table() + db.create_all(), which run
BEFORE flask_migrate.upgrade() at startup — this revision only patches columns,
indexes and seed rows that ALTER-only upgrades need.

Every step is guarded (checks the live schema first) because an existing box
may have any subset already applied by the old ad-hoc path. Unlike that path,
a genuine failure here RAISES — the app refuses to start on a half-upgraded
database instead of limping along.

Revision ID: 0001_baseline
Revises:
Create Date: 2026-07-16
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = '0001_baseline'
down_revision = None
branch_labels = None
depends_on = None


def _columns(bind, table):
    """Column names of `table`, or [] if the table doesn't exist."""
    return [r[1] for r in bind.exec_driver_sql(f'PRAGMA table_info("{table}")')]


def upgrade():
    bind = op.get_bind()

    def add_column(table, column, decl):
        """ALTER TABLE ... ADD COLUMN, only if the table exists and lacks it.
        Returns True when the column was actually added."""
        cols = _columns(bind, table)
        if cols and column not in cols:
            bind.exec_driver_sql(f'ALTER TABLE {table} ADD COLUMN {column} {decl}')
            return True
        return False

    # tblBattleMaps.sort_order — seed from map_id so current maps keep their order
    if add_column('tblBattleMaps', 'sort_order', 'INTEGER DEFAULT 0'):
        bind.exec_driver_sql('UPDATE tblBattleMaps SET sort_order = map_id')

    # relay_roll_id on both roll tables — dedup key for relay-forwarded rolls
    add_column('tblRollLog', 'relay_roll_id', 'INTEGER')
    add_column('tblDiceRolls', 'relay_roll_id', 'INTEGER')

    # tblTokenPositions.relay_seq — last relay write-sequence per token
    add_column('tblTokenPositions', 'relay_seq', 'INTEGER DEFAULT 0')

    # tblCharacters.subclass / .genre — sheet archetype + genre-pack skin
    add_column('tblCharacters', 'subclass', "TEXT DEFAULT ''")
    add_column('tblCharacters', 'genre', "TEXT DEFAULT 'fantasy'")

    # tblServersIP.version — app/firmware version a discovered device reports
    add_column('tblServersIP', 'version', 'TEXT')

    # media identity + metadata-queue columns on both media tables
    for table in ('tblMusic', 'tblVideoMedia'):
        add_column(table, 'videoId', 'TEXT')
        add_column(table, 'displayName', 'TEXT')
        add_column(table, 'metaStatus', 'INTEGER DEFAULT 0')
        add_column(table, 'metaNextRetry', 'TEXT')

    # tblPlaylistQueue.next_retry — download-retry backoff gate
    add_column('tblPlaylistQueue', 'next_retry', 'TEXT')

    # partial UNIQUE index on videoId (must come after the ALTERs above)
    for table, index in (('tblMusic', 'idx_tblMusic_videoId'),
                         ('tblVideoMedia', 'idx_tblVideoMedia_videoId')):
        if _columns(bind, table):
            bind.exec_driver_sql(
                f'CREATE UNIQUE INDEX IF NOT EXISTS {index} '
                f'ON {table}(videoId) WHERE videoId IS NOT NULL')

    # lutStatus row 5 "Unavailable" — the JSON loader only seeds an EMPTY table,
    # so upgraded DBs need the insert here
    if _columns(bind, 'lutStatus'):
        has5 = bind.exec_driver_sql(
            'SELECT 1 FROM lutStatus WHERE status_ID = 5').fetchone()
        if not has5:
            bind.exec_driver_sql(
                "INSERT INTO lutStatus(status_ID, status) VALUES (5, 'Unavailable')")


def downgrade():
    # Pre-baseline schemas are not restorable — the old ad-hoc path had no
    # downgrade either. Intentionally a no-op.
    pass
