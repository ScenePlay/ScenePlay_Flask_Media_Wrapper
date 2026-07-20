"""The legacy no-video-id intake path must queue METADATA alongside the download.

Non-YouTube URLs (no parseable video id) fall into sql._enqueue_legacy, whose
CRUD insert leaves metaStatus at the column default 0 — historically those rows
never got metadata. The fix sets metaStatus=1 and raises meta_que_switch, same
contract as the id-based path. Throwaway sqlite file, sql.database monkeypatched
(pattern from test_queue_backoff.py).
"""

import sqlite3

import pytest

import sql
from sql import enqueue_single, select_Meta_Que_Next


@pytest.fixture
def qdb(tmp_path, monkeypatch):
    db = str(tmp_path / 'media.db')
    conn = sqlite3.connect(db)
    c = conn.cursor()
    c.execute("CREATE TABLE tblMusic (song_id INTEGER PRIMARY KEY AUTOINCREMENT, path TEXT, song TEXT, pTimes INT, playedDTTM TEXT, active INT, genre INT, que INT, urlSource TEXT, dnLoadStatus INT, videoId TEXT, displayName TEXT, metaStatus INT DEFAULT 0, metaNextRetry TEXT)")
    c.execute("CREATE TABLE tblVideoMedia (video_ID INTEGER PRIMARY KEY AUTOINCREMENT, path TEXT, title TEXT, pTimes INT, playedDTTM TEXT, active INT, genre INT, que INT, urlSource TEXT, dnLoadStatus INT, videoId TEXT, displayName TEXT, metaStatus INT DEFAULT 0, metaNextRetry TEXT)")
    c.execute("CREATE TABLE tblMediaMetadata (metadata_id INTEGER PRIMARY KEY, media_type TEXT, media_id INT, retry_count INT DEFAULT 0)")
    c.execute("CREATE TABLE tblAppSettings (name TEXT, value TEXT, typevalue TEXT)")
    c.execute("INSERT INTO tblAppSettings(name, value, typevalue) VALUES ('yt_que_switch', '0', 'int')")
    c.execute("INSERT INTO tblAppSettings(name, value, typevalue) VALUES ('meta_que_switch', '0', 'int')")
    conn.commit()
    conn.close()
    monkeypatch.setattr(sql, 'database', db)
    return db


def _flag(db, name):
    conn = sqlite3.connect(db)
    val = conn.execute("SELECT value FROM tblAppSettings WHERE name = ?", (name,)).fetchone()[0]
    conn.close()
    return str(val)


NON_YT_URL = 'https://example.com/some/clip'


def test_legacy_mp3_queues_download_and_metadata(qdb):
    pk, created, reason = enqueue_single(NON_YT_URL, 'mp3', 0, 'My Song')
    assert created and reason == ''

    conn = sqlite3.connect(qdb)
    dn, meta, url = conn.execute(
        "SELECT dnLoadStatus, metaStatus, urlSource FROM tblMusic WHERE song_id = ?", (pk,)).fetchone()
    conn.close()
    assert (dn, meta) == (1, 1)
    assert url == NON_YT_URL
    assert _flag(qdb, 'yt_que_switch') == '1'
    assert _flag(qdb, 'meta_que_switch') == '1'
    # and the metadata worker's selector actually picks it up
    jobs = select_Meta_Que_Next()
    assert [(j[0], j[1], j[2]) for j in jobs] == [(pk, NON_YT_URL, 'music')]


def test_legacy_mp4_queues_download_and_metadata(qdb):
    pk, created, reason = enqueue_single(NON_YT_URL, 'mp4', 0, 'My Clip')
    assert created and reason == ''

    conn = sqlite3.connect(qdb)
    dn, meta = conn.execute(
        "SELECT dnLoadStatus, metaStatus FROM tblVideoMedia WHERE video_ID = ?", (pk,)).fetchone()
    conn.close()
    assert (dn, meta) == (1, 1)
    assert _flag(qdb, 'meta_que_switch') == '1'
    jobs = select_Meta_Que_Next()
    assert [(j[0], j[1], j[2]) for j in jobs] == [(pk, NON_YT_URL, 'video')]


def test_legacy_without_name_still_rejected(qdb):
    # unchanged contract: no video id AND no name -> refused, nothing queued
    pk, created, reason = enqueue_single(NON_YT_URL, 'mp3', 0, '')
    assert pk is None and not created and reason
    assert _flag(qdb, 'meta_que_switch') == '0'
