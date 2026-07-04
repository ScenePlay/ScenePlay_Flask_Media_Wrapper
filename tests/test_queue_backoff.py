"""DB-backed tests for queue retry backoff and the idle-switch guards.

A throwaway sqlite file with just the queue tables, injected by monkeypatching
sql.database — no app boot, no network. Covers the two stranding bugs:
- a worker switching itself off while rows wait out a retry backoff
- playlist retries burning seconds apart with no backoff gate
"""

import sqlite3
from datetime import datetime, timedelta

import pytest

import sql
from sql import (select_Playlist_Que_Next, update_playlist_status,
                 playlist_pending_any, meta_pending_any, select_Meta_Que_Next,
                 requeue_metadata_if_missing)


def _ts(minutes_from_now):
    return (datetime.utcnow() + timedelta(minutes=minutes_from_now)).strftime('%Y-%m-%d %H:%M:%S')


@pytest.fixture
def qdb(tmp_path, monkeypatch):
    db = str(tmp_path / 'queues.db')
    conn = sqlite3.connect(db)
    c = conn.cursor()
    c.execute("CREATE TABLE tblPlaylistQueue (playlist_id INTEGER PRIMARY KEY AUTOINCREMENT, url TEXT, media_type TEXT, scene_ID INT, status INT DEFAULT 1, retry_count INT DEFAULT 0, last_error TEXT, created_at TEXT, next_retry TEXT)")
    c.execute("CREATE TABLE tblMusic (song_id INTEGER PRIMARY KEY, urlSource TEXT, metaStatus INT DEFAULT 0, metaNextRetry TEXT)")
    c.execute("CREATE TABLE tblVideoMedia (video_id INTEGER PRIMARY KEY, urlSource TEXT, metaStatus INT DEFAULT 0, metaNextRetry TEXT)")
    c.execute("CREATE TABLE tblMediaMetadata (metadata_id INTEGER PRIMARY KEY, media_type TEXT, media_id INT, retry_count INT DEFAULT 0)")
    c.execute("CREATE TABLE tblAppSettings (name TEXT, value TEXT, typevalue TEXT)")
    c.execute("INSERT INTO tblAppSettings(name, value, typevalue) VALUES ('meta_que_switch', '0', 'int')")
    conn.commit()
    conn.close()
    monkeypatch.setattr(sql, 'database', db)
    return db


def _add_playlist(db, status=1, next_retry=None):
    conn = sqlite3.connect(db)
    c = conn.cursor()
    c.execute("INSERT INTO tblPlaylistQueue(url, media_type, scene_ID, status, next_retry) VALUES ('u', 'music', 0, ?, ?)",
              (status, next_retry))
    conn.commit()
    pid = c.lastrowid
    conn.close()
    return pid


def _playlist_row(db, pid):
    conn = sqlite3.connect(db)
    c = conn.cursor()
    c.execute("SELECT status, retry_count, last_error, next_retry FROM tblPlaylistQueue WHERE playlist_id = ?", (pid,))
    row = c.fetchone()
    conn.close()
    return row


def _add_music(db, meta_status=1, next_retry=None):
    conn = sqlite3.connect(db)
    c = conn.cursor()
    c.execute("INSERT INTO tblMusic(urlSource, metaStatus, metaNextRetry) VALUES ('https://u', ?, ?)",
              (meta_status, next_retry))
    conn.commit()
    conn.close()


class TestPlaylistBackoff:
    def test_no_backoff_is_selected(self, qdb):
        pid = _add_playlist(qdb)
        assert select_Playlist_Que_Next()[0][0] == pid

    def test_future_backoff_is_not_selected(self, qdb):
        _add_playlist(qdb, next_retry=_ts(+5))
        assert select_Playlist_Que_Next() == []

    def test_expired_backoff_is_selected(self, qdb):
        pid = _add_playlist(qdb, next_retry=_ts(-5))
        assert select_Playlist_Que_Next()[0][0] == pid

    def test_update_sets_backoff_and_keeps_counters(self, qdb):
        pid = _add_playlist(qdb)
        update_playlist_status(pid, 1, retry_count=1, last_error='boom', next_retry=_ts(+2))
        status, retries, err, nr = _playlist_row(qdb, pid)
        assert (status, retries, err) == (1, 1, 'boom')
        assert nr is not None

    def test_update_clears_backoff_on_other_transitions(self, qdb):
        pid = _add_playlist(qdb, next_retry=_ts(+2))
        update_playlist_status(pid, 2)   # Processing must not carry a stale gate
        status, retries, err, nr = _playlist_row(qdb, pid)
        assert status == 2 and nr is None

    def test_pending_any_sees_backoff_row(self, qdb):
        # The stranding case: not selectable, but the worker must NOT go idle.
        _add_playlist(qdb, next_retry=_ts(+5))
        assert select_Playlist_Que_Next() == []
        assert playlist_pending_any() is True

    def test_pending_any_false_when_queue_done(self, qdb):
        _add_playlist(qdb, status=3)
        _add_playlist(qdb, status=4)
        assert playlist_pending_any() is False


class TestMetaPending:
    def test_backoff_row_pending_but_not_selectable(self, qdb):
        # The stranding case on the media tables.
        _add_music(qdb, next_retry=_ts(+5))
        assert select_Meta_Que_Next() == []
        assert meta_pending_any() is True

    def test_expired_backoff_is_selectable(self, qdb):
        _add_music(qdb, next_retry=_ts(-5))
        assert len(select_Meta_Que_Next()) == 1

    def test_no_pending_when_finished(self, qdb):
        _add_music(qdb, meta_status=3)
        assert meta_pending_any() is False

    def test_video_rows_count_as_pending(self, qdb):
        conn = sqlite3.connect(qdb)
        conn.execute("INSERT INTO tblVideoMedia(urlSource, metaStatus) VALUES ('https://u', 1)")
        conn.commit()
        conn.close()
        assert meta_pending_any() is True


def _music_state(db, pk=1):
    conn = sqlite3.connect(db)
    c = conn.cursor()
    c.execute("SELECT metaStatus, metaNextRetry FROM tblMusic WHERE song_id = ?", (pk,))
    row = c.fetchone()
    c.execute("SELECT value FROM tblAppSettings WHERE name = 'meta_que_switch'")
    switch = c.fetchone()[0]
    conn.close()
    return row[0], row[1], str(switch)


class TestRequeueMetadataIfMissing:
    def test_never_extracted_row_requeues(self, qdb):
        _add_music(qdb, meta_status=0)
        assert requeue_metadata_if_missing('music', 1) is True
        status, next_retry, switch = _music_state(qdb)
        assert (status, next_retry, switch) == (1, None, '1')

    def test_failed_row_requeues_and_resets_retries(self, qdb):
        _add_music(qdb, meta_status=4, next_retry=_ts(+5))
        conn = sqlite3.connect(qdb)
        conn.execute("INSERT INTO tblMediaMetadata(media_type, media_id, retry_count) VALUES ('music', 1, 3)")
        conn.commit()
        conn.close()
        assert requeue_metadata_if_missing('music', 1) is True
        status, next_retry, switch = _music_state(qdb)
        assert (status, next_retry, switch) == (1, None, '1')   # stale backoff cleared
        conn = sqlite3.connect(qdb)
        retries = conn.execute("SELECT retry_count FROM tblMediaMetadata WHERE media_type='music' AND media_id=1").fetchone()[0]
        conn.close()
        assert retries == 0   # a full fresh set of attempts, not the leftover one

    def test_unavailable_row_is_left_alone(self, qdb):
        _add_music(qdb, meta_status=5)
        assert requeue_metadata_if_missing('music', 1) is False
        status, _, switch = _music_state(qdb)
        assert (status, switch) == (5, '0')

    def test_finished_row_is_left_alone(self, qdb):
        _add_music(qdb, meta_status=3)
        assert requeue_metadata_if_missing('music', 1) is False
        assert _music_state(qdb)[0] == 3

    def test_row_without_url_is_left_alone(self, qdb):
        conn = sqlite3.connect(qdb)
        conn.execute("INSERT INTO tblMusic(urlSource, metaStatus) VALUES ('', 0)")
        conn.commit()
        conn.close()
        assert requeue_metadata_if_missing('music', 1) is False
        assert _music_state(qdb)[0] == 0
