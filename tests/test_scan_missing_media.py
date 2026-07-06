"""Utilities 'Scan Media Files' — sql.scan_missing_media on a scratch db.

Status lexicon: 1 Queued, 2 Processing, 3 Finished, 4 Failed, 5 Unavailable.
"""

import sqlite3

import pytest

import sql


@pytest.fixture
def env(tmp_path, monkeypatch):
    db = str(tmp_path / 'scan.db')
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE tblMusic (song_id INTEGER PRIMARY KEY, path TEXT, song TEXT, "
                 "urlSource TEXT, dnLoadStatus INT, videoId TEXT)")
    conn.execute("CREATE TABLE tblVideoMedia (video_ID INTEGER PRIMARY KEY, path TEXT, title TEXT, "
                 "urlSource TEXT, dnLoadStatus INT, videoId TEXT)")
    conn.execute("CREATE TABLE tblAppSettings (name TEXT, value TEXT, typevalue TEXT)")
    # the switch row always exists on a real server (seeded at first boot);
    # the flag helper is UPDATE-only, so seed it here too
    conn.execute("INSERT INTO tblAppSettings VALUES ('yt_que_switch', '0', 'int')")
    conn.commit()
    conn.close()
    monkeypatch.setattr(sql, 'database', db)
    return {'db': db, 'dir': tmp_path}


def _song(env, name, status, url='https://u', path=None):
    path = path if path is not None else str(env['dir']) + '/'
    conn = sqlite3.connect(env['db'])
    conn.execute("INSERT INTO tblMusic(path, song, urlSource, dnLoadStatus, videoId) VALUES (?,?,?,?,?)",
                 (path, name, url, status, 'vid_' + name))
    conn.commit()
    conn.close()


def _statuses(env):
    conn = sqlite3.connect(env['db'])
    rows = dict(conn.execute("SELECT song, dnLoadStatus FROM tblMusic").fetchall())
    conn.close()
    return rows


def test_missing_finished_and_failed_requeue(env):
    (env['dir'] / 'present.mp3').write_bytes(b'x')
    _song(env, 'present.mp3', 3)     # finished, file exists  -> untouched
    _song(env, 'gone.mp3', 3)        # finished, file missing -> requeued
    _song(env, 'failed.mp3', 4)      # failed                 -> retried
    out = sql.scan_missing_media()
    assert out == {'music': 2, 'video': 0}
    s = _statuses(env)
    assert s['present.mp3'] == 3 and s['gone.mp3'] == 1 and s['failed.mp3'] == 1
    # downloader switch woken
    conn = sqlite3.connect(env['db'])
    assert conn.execute("SELECT value FROM tblAppSettings WHERE name='yt_que_switch'").fetchone()[0] == '1'
    conn.close()


def test_untouchable_statuses_and_legacy_left_alone(env):
    _song(env, 'queued.mp3', 1)          # already queued
    _song(env, 'downloading.mp3', 2)     # mid-download
    _song(env, 'dead.mp3', 5)            # permanently unavailable
    _song(env, 'legacy.mp3', 3, url='')  # nothing to download from
    out = sql.scan_missing_media()
    assert out == {'music': 0, 'video': 0}
    s = _statuses(env)
    assert s == {'queued.mp3': 1, 'downloading.mp3': 2, 'dead.mp3': 5, 'legacy.mp3': 3}


def test_video_table_scanned_too(env):
    conn = sqlite3.connect(env['db'])
    conn.execute("INSERT INTO tblVideoMedia(path, title, urlSource, dnLoadStatus, videoId) "
                 "VALUES (?, 'missing.mp4', 'https://u', 3, 'v1')", (str(env['dir']) + '/',))
    conn.commit()
    conn.close()
    assert sql.scan_missing_media() == {'music': 0, 'video': 1}
