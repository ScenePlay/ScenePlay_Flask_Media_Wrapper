"""Versioned schema migrations: flask_migrate.upgrade() (run at app startup)
must bring a pre-Alembic database up to the current schema, record the
revision in alembic_version, and pass through cleanly on databases that are
already current — including ones the old ad-hoc ALTER blocks half-upgraded.
"""
import os
import sqlite3

import pytest
from flask import Flask
from flask_migrate import Migrate, upgrade

from extensions import db

MIGRATIONS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'migrations')

# Table shapes as they were BEFORE the columns the baseline revision adds.
OLD_SCHEMA = [
    "CREATE TABLE tblMusic (song_id INTEGER PRIMARY KEY, path TEXT, song TEXT, pTimes INT, playedDTTM TEXT, active INT, genre INT, que INT, urlSource TEXT, dnLoadStatus INT)",
    "CREATE TABLE tblVideoMedia (video_ID INTEGER PRIMARY KEY, path TEXT, title TEXT, pTimes INT, playedDTTM TEXT, active INT, genre INT, que INT, urlSource TEXT, dnLoadStatus INT)",
    "CREATE TABLE tblBattleMaps (map_id INTEGER PRIMARY KEY, name TEXT)",
    "CREATE TABLE tblCharacters (character_id INTEGER PRIMARY KEY, user_id INT, name TEXT)",
    "CREATE TABLE tblServersIP (ServerIP_ID INTEGER PRIMARY KEY, serverName TEXT, ipAddress TEXT)",
    "CREATE TABLE tblPlaylistQueue (playlist_id INTEGER PRIMARY KEY, url TEXT)",
    "CREATE TABLE tblRollLog (roll_id INTEGER PRIMARY KEY, result INT)",
    "CREATE TABLE lutStatus (pkey INTEGER PRIMARY KEY, status_ID INT, status TEXT)",
    "CREATE TABLE tblMediaMetadata (metadata_id INTEGER PRIMARY KEY, media_type TEXT, media_id INT, title TEXT, raw_json TEXT)",
]

HEAD = '0002_slim_raw_json'


def columns(path, table):
    conn = sqlite3.connect(path)
    cols = [r[1] for r in conn.execute(f'PRAGMA table_info("{table}")')]
    conn.close()
    return cols


def q(path, sql_text, args=()):
    conn = sqlite3.connect(path)
    rows = conn.execute(sql_text, args).fetchall()
    conn.close()
    return rows


@pytest.fixture()
def old_db(tmp_path):
    """A file database with the pre-upgrade schema and a little data."""
    path = str(tmp_path / 'old.db')
    conn = sqlite3.connect(path)
    for stmt in OLD_SCHEMA:
        conn.execute(stmt)
    conn.execute("INSERT INTO tblBattleMaps(map_id, name) VALUES (7, 'Crypt')")
    conn.execute("INSERT INTO lutStatus(status_ID, status) VALUES (1, 'Queued')")
    conn.commit()
    conn.close()
    return path


def migrated_app(db_path):
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    db.init_app(app)
    Migrate(app, db, directory=MIGRATIONS_DIR)
    return app


def run_upgrade(db_path):
    app = migrated_app(db_path)
    with app.app_context():
        upgrade()


class TestBaselineUpgrade:
    def test_old_db_gains_all_columns(self, old_db):
        run_upgrade(old_db)
        for col in ('videoId', 'displayName', 'metaStatus', 'metaNextRetry'):
            assert col in columns(old_db, 'tblMusic')
            assert col in columns(old_db, 'tblVideoMedia')
        assert 'sort_order' in columns(old_db, 'tblBattleMaps')
        assert 'subclass' in columns(old_db, 'tblCharacters')
        assert 'genre' in columns(old_db, 'tblCharacters')
        assert 'version' in columns(old_db, 'tblServersIP')
        assert 'next_retry' in columns(old_db, 'tblPlaylistQueue')
        assert 'relay_roll_id' in columns(old_db, 'tblRollLog')

    def test_sort_order_seeded_from_map_id(self, old_db):
        run_upgrade(old_db)
        assert q(old_db, "SELECT sort_order FROM tblBattleMaps WHERE map_id=7") == [(7,)]

    def test_video_id_unique_index_created(self, old_db):
        run_upgrade(old_db)
        names = {r[0] for r in q(old_db,
                 "SELECT name FROM sqlite_master WHERE type='index'")}
        assert {'idx_tblMusic_videoId', 'idx_tblVideoMedia_videoId'} <= names

    def test_lutstatus_unavailable_seeded_once(self, old_db):
        run_upgrade(old_db)
        assert q(old_db, "SELECT status FROM lutStatus WHERE status_ID=5") == [('Unavailable',)]
        run_upgrade(old_db)   # second boot: no duplicate seed
        assert q(old_db, "SELECT COUNT(*) FROM lutStatus WHERE status_ID=5") == [(1,)]

    def test_revision_recorded_and_second_run_noop(self, old_db):
        run_upgrade(old_db)
        assert q(old_db, "SELECT version_num FROM alembic_version") == [(HEAD,)]
        run_upgrade(old_db)   # idempotent
        assert q(old_db, "SELECT version_num FROM alembic_version") == [(HEAD,)]

    def test_half_upgraded_db_passes(self, old_db):
        """A box the old ad-hoc path partially upgraded (some columns already
        present, no alembic_version) must migrate cleanly, not crash on
        duplicate-column errors."""
        conn = sqlite3.connect(old_db)
        conn.execute("ALTER TABLE tblMusic ADD COLUMN videoId TEXT")
        conn.execute("ALTER TABLE tblCharacters ADD COLUMN subclass TEXT DEFAULT ''")
        conn.commit()
        conn.close()
        run_upgrade(old_db)
        assert 'metaStatus' in columns(old_db, 'tblMusic')      # the rest arrived
        assert 'genre' in columns(old_db, 'tblCharacters')

    def test_raw_json_slimmed_to_whitelist(self, old_db):
        """0002: fat yt-dlp dumps shrink to the whitelisted keys; junk that
        doesn't parse becomes NULL; the file itself shrinks (VACUUM ran)."""
        import json
        fat = json.dumps({
            'id': 'abc123', 'title': 'A Song', 'artist': 'Someone',
            'tags': ['ambient'], 'chapters': None,
            'formats': [{'url': 'https://x/' + 'f' * 100_000}],
            'http_headers': {'User-Agent': 'y' * 50_000},
        })
        conn = sqlite3.connect(old_db)
        conn.execute("INSERT INTO tblMediaMetadata(media_type, media_id, title, raw_json) "
                     "VALUES ('music', 1, 'A Song', ?)", (fat,))
        conn.execute("INSERT INTO tblMediaMetadata(media_type, media_id, title, raw_json) "
                     "VALUES ('music', 2, 'Broken', 'not json{')")
        conn.commit()
        conn.close()
        size_before = os.path.getsize(old_db)

        run_upgrade(old_db)

        slim = json.loads(q(old_db,
                            "SELECT raw_json FROM tblMediaMetadata WHERE media_id=1")[0][0])
        assert slim == {'id': 'abc123', 'artist': 'Someone', 'tags': ['ambient']}
        assert 'formats' not in slim and 'http_headers' not in slim
        assert q(old_db, "SELECT raw_json FROM tblMediaMetadata WHERE media_id=2") == [(None,)]
        assert os.path.getsize(old_db) < size_before   # VACUUM reclaimed the blob

    def test_missing_optional_tables_are_skipped(self, tmp_path):
        """Very old DBs lack some tables entirely (e.g. tblDiceRolls,
        tblTokenPositions). The guards skip them; create_table()/create_all()
        provide them with current shape at startup."""
        path = str(tmp_path / 'tiny.db')
        conn = sqlite3.connect(path)
        conn.execute(OLD_SCHEMA[0])   # only tblMusic
        conn.commit()
        conn.close()
        run_upgrade(path)
        assert 'videoId' in columns(path, 'tblMusic')
