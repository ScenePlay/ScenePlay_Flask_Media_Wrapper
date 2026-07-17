"""Slim tblMediaMetadata.raw_json to the whitelisted keys.

The metadata worker used to store the COMPLETE yt-dlp info dict per media row
(~175 KB each — mostly `formats` with per-variant fragment URLs and HTTP
headers), which nothing ever read back and which grew ScenePlay.db to ~86 MB.
meta_que.py now writes only RAW_JSON_KEYS; this revision rewrites existing
rows to the same shape (unparseable blobs become NULL) and VACUUMs to hand the
space back to the filesystem — important on Pi-class boxes and for every
backup zip built from this file.

Rows are processed in small batches so a large table never loads at once.

Revision ID: 0002_slim_raw_json
Revises: 0001_baseline
Create Date: 2026-07-16
"""
import json

from alembic import op

# revision identifiers, used by Alembic.
revision = '0002_slim_raw_json'
down_revision = '0001_baseline'
branch_labels = None
depends_on = None

# Frozen copy of meta_que.RAW_JSON_KEYS at the time of this revision
# (migrations never import app code — they must replay identically forever).
RAW_JSON_KEYS = (
    'id', 'webpage_url', 'extractor',
    'channel', 'channel_id', 'uploader_id',
    'tags', 'like_count', 'comment_count', 'average_rating',
    'age_limit', 'availability', 'live_status',
    'album', 'artist', 'track', 'release_year',
    'chapters',
)

BATCH = 20   # ≤ 2 MB/row cap → worst case ~40 MB in flight


def upgrade():
    bind = op.get_bind()
    cols = [r[1] for r in bind.exec_driver_sql('PRAGMA table_info("tblMediaMetadata")')]
    if 'raw_json' in cols:
        last_pk = 0
        while True:
            rows = bind.exec_driver_sql(
                "SELECT metadata_id, raw_json FROM tblMediaMetadata "
                "WHERE metadata_id > ? AND raw_json IS NOT NULL AND raw_json <> '' "
                "ORDER BY metadata_id LIMIT ?", (last_pk, BATCH)).fetchall()
            if not rows:
                break
            for pk, raw in rows:
                try:
                    info = json.loads(raw)
                    slim = (json.dumps({k: info[k] for k in RAW_JSON_KEYS
                                        if info.get(k) is not None})
                            if isinstance(info, dict) else None)
                except ValueError:
                    slim = None
                bind.exec_driver_sql(
                    "UPDATE tblMediaMetadata SET raw_json = ? WHERE metadata_id = ?",
                    (slim, pk))
            last_pk = rows[-1][0]

    # VACUUM cannot run inside the migration transaction
    with op.get_context().autocommit_block():
        op.execute('VACUUM')


def downgrade():
    # The discarded format tables are unrecoverable (and were never read).
    pass
