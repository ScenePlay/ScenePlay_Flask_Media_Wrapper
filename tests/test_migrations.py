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

HEAD = '0016_library_game_system'


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
        for col in ('videoId', 'displayName', 'metaStatus', 'metaNextRetry',
                    'dnLastError'):
            assert col in columns(old_db, 'tblMusic')
            assert col in columns(old_db, 'tblVideoMedia')
        assert 'sort_order' in columns(old_db, 'tblBattleMaps')
        assert 'subclass' in columns(old_db, 'tblCharacters')
        assert 'genre' in columns(old_db, 'tblCharacters')
        assert 'version' in columns(old_db, 'tblServersIP')
        assert 'next_retry' in columns(old_db, 'tblPlaylistQueue')
        assert 'relay_roll_id' in columns(old_db, 'tblRollLog')
        for col in ('artist', 'artist_source', 'origin_playlist', 'origin_playlist_title'):
            assert col in columns(old_db, 'tblMediaMetadata')   # 0011

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


class TestSessionNotesCarryOver:
    """0006: tblSessions.dm_notes content becomes the first tblSessionNotes row."""

    @pytest.fixture()
    def sessions_db(self, old_db):
        conn = sqlite3.connect(old_db)
        conn.execute("CREATE TABLE tblSessions (session_id INTEGER PRIMARY KEY, "
                     "title TEXT, dm_notes TEXT, created_at TEXT)")
        conn.execute("INSERT INTO tblSessions VALUES (1, 'Camp A', 'plot hooks', '2026-01-01 10:00:00')")
        conn.execute("INSERT INTO tblSessions VALUES (2, 'Camp B', '', '2026-01-02 10:00:00')")
        conn.execute("INSERT INTO tblSessions VALUES (3, 'Camp C', '   ', '2026-01-03 10:00:00')")
        conn.commit()
        conn.close()
        return old_db

    def test_dm_notes_copied_once(self, sessions_db):
        run_upgrade(sessions_db)
        rows = q(sessions_db,
                 "SELECT session_id, title, body, created_at FROM tblSessionNotes ORDER BY session_id")
        assert rows == [(1, 'Session notes', 'plot hooks', '2026-01-01 10:00:00')]
        # blank / whitespace-only dm_notes must NOT spawn empty notes
        # second boot: no duplicate copy
        run_upgrade(sessions_db)
        assert q(sessions_db, "SELECT COUNT(*) FROM tblSessionNotes") == [(1,)]
        # legacy column left intact (nothing writes it anymore, nothing lost)
        assert q(sessions_db, "SELECT dm_notes FROM tblSessions WHERE session_id=1") == [('plot hooks',)]

    def test_no_sessions_table_is_noop(self, old_db):
        run_upgrade(old_db)   # old_db has no tblSessions at all
        assert q(old_db, "SELECT version_num FROM alembic_version") == [(HEAD,)]

    def test_session_with_existing_notes_not_recopied(self, sessions_db):
        run_upgrade(sessions_db)
        conn = sqlite3.connect(sessions_db)
        # the DM deletes the migrated note, then... a later boot must not resurrect it
        conn.execute("DELETE FROM tblSessionNotes WHERE session_id=1")
        conn.execute("INSERT INTO tblSessionNotes(session_id, title, body, sort_order, created_at, updated_at) "
                     "VALUES (1, 'fresh', 'x', 0, '2026-02-01 00:00:00', '2026-02-01 00:00:00')")
        conn.commit(); conn.close()
        run_upgrade(sessions_db)
        assert q(sessions_db, "SELECT title FROM tblSessionNotes WHERE session_id=1") == [('fresh',)]


def test_0012_prunes_links_to_missing_scenes(tmp_path):
    """Links to a deleted scene or the All Stop pseudo-scene (-1) go; links to
    real scenes stay."""
    path = str(tmp_path / 'links.db')
    conn = sqlite3.connect(path)
    for stmt in OLD_SCHEMA:
        conn.execute(stmt)
    # created lower-case on purpose: the live database's sqlite_master holds
    # these names in a different case than the code writes them
    conn.execute("CREATE TABLE tblscenes (scene_ID INTEGER PRIMARY KEY, sceneName TEXT)")
    conn.execute("CREATE TABLE tblmusicscene (musicScene_ID INTEGER PRIMARY KEY, scene_ID INT, song_ID INT)")
    conn.execute("CREATE TABLE tblvideoscene (videoScene_ID INTEGER PRIMARY KEY, scene_ID INT, video_ID INT)")
    conn.execute("INSERT INTO tblScenes VALUES (5, 'Rock')")
    conn.executemany("INSERT INTO tblMusicScene (scene_ID, song_ID) VALUES (?,?)", [(5, 1), (-1, 2), (99, 3), (None, 4)])
    conn.executemany("INSERT INTO tblVideoScene (scene_ID, video_ID) VALUES (?,?)", [(5, 1), (-1, 1)])
    conn.commit(); conn.close()
    run_upgrade(path)
    assert q(path, "SELECT scene_ID, song_ID FROM tblMusicScene") == [(5, 1)]
    assert q(path, "SELECT scene_ID, video_ID FROM tblVideoScene") == [(5, 1)]


class TestSessionGameSystem:
    """0014: tblSessions gains game_system / system_settings with the D&D 5e
    default; existing rows read as 5e; the guard is case-insensitive."""

    @pytest.fixture(params=['tblSessions', 'tblsessions'])
    def sessions_db(self, old_db, request):
        conn = sqlite3.connect(old_db)
        conn.execute(f"CREATE TABLE {request.param} (session_id INTEGER PRIMARY KEY, "
                     "title TEXT, dm_notes TEXT, created_at TEXT)")
        conn.execute(f"INSERT INTO {request.param} VALUES (1, 'Camp A', '', '2026-01-01 10:00:00')")
        conn.commit()
        conn.close()
        return old_db

    def test_columns_added_with_defaults(self, sessions_db):
        run_upgrade(sessions_db)
        cols = columns(sessions_db, 'tblSessions')
        assert 'game_system' in cols and 'system_settings' in cols
        assert q(sessions_db, "SELECT game_system, system_settings FROM tblSessions") == [('dnd5e', '{}')]
        run_upgrade(sessions_db)   # second boot: no duplicate-column error
        assert q(sessions_db, "SELECT version_num FROM alembic_version") == [(HEAD,)]


class TestCharacterGameSystem:
    """0015: per-character game system + DCC sheet columns, case-insensitive guard."""

    @pytest.fixture(params=['tblCharacters', 'tblcharacters'])
    def chars_db(self, tmp_path, request):
        path = str(tmp_path / 'chars.db')
        conn = sqlite3.connect(path)
        for stmt in OLD_SCHEMA:
            if 'tblCharacters' in stmt:
                stmt = stmt.replace('tblCharacters', request.param)
            conn.execute(stmt)
        conn.execute(f"INSERT INTO {request.param}(character_id, user_id, name) VALUES (1, 1, 'Carl')")
        conn.execute("CREATE TABLE tblCharacterSkills (skill_id INTEGER PRIMARY KEY, character_id INT, skill_name TEXT, bonus INT, proficient INT, order_by INT)")
        conn.execute("CREATE TABLE tblCharacterInventory (item_id INTEGER PRIMARY KEY, character_id INT, item_name TEXT, quantity INT, weight TEXT, notes TEXT, equipped INT, order_by INT)")
        conn.execute("INSERT INTO tblCharacterSkills VALUES (1, 1, 'Sneak', 2, 1, 0)")
        conn.commit(); conn.close()
        return path

    def test_columns_added_with_defaults(self, chars_db):
        run_upgrade(chars_db)
        assert {'game_system', 'dcc_json'} <= set(columns(chars_db, 'tblCharacters'))
        assert q(chars_db, "SELECT game_system, dcc_json FROM tblCharacters") == [('dnd5e', '{}')]
        assert {'category', 'stat'} <= set(columns(chars_db, 'tblCharacterSkills'))
        assert q(chars_db, "SELECT category, stat, bonus FROM tblCharacterSkills") == [('', '', 2)]
        assert 'hotlist' in columns(chars_db, 'tblCharacterInventory')
        run_upgrade(chars_db)   # idempotent
        assert q(chars_db, "SELECT version_num FROM alembic_version") == [(HEAD,)]


class TestLibraryGameSystem:
    """0016: the three reference libraries gain game_system (default dnd5e)."""

    def test_columns_added(self, tmp_path):
        path = str(tmp_path / 'lib.db')
        conn = sqlite3.connect(path)
        for stmt in OLD_SCHEMA:
            conn.execute(stmt)
        conn.execute("CREATE TABLE tblskillslibrary (skill_lib_id INTEGER PRIMARY KEY, api_index TEXT, name TEXT, ability_score TEXT, description TEXT, source TEXT, created_at TEXT)")
        conn.execute("INSERT INTO tblskillslibrary(name, ability_score, source, created_at) VALUES ('Stealth', 'DEX', 'srd', 't')")
        conn.commit(); conn.close()
        run_upgrade(path)
        assert 'game_system' in columns(path, 'tblskillslibrary')
        assert q(path, "SELECT game_system FROM tblskillslibrary") == [('dnd5e',)]
        run_upgrade(path)
        assert q(path, "SELECT version_num FROM alembic_version") == [(HEAD,)]
