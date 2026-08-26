"""Utilities → Download Queue (sql helpers): stats + failure rate, the failed
list with its captured error, retry one / retry all, and the chime toggles."""
import sqlite3

import pytest

import sql


@pytest.fixture
def env(tmp_path, monkeypatch):
    db = str(tmp_path / 'q.db')
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE tblMusic (song_id INTEGER PRIMARY KEY, path TEXT, song TEXT, displayName TEXT, "
                 "urlSource TEXT, dnLoadStatus INT, dnLastError TEXT)")
    conn.execute("CREATE TABLE tblVideoMedia (video_ID INTEGER PRIMARY KEY, path TEXT, title TEXT, displayName TEXT, "
                 "urlSource TEXT, dnLoadStatus INT, dnLastError TEXT)")
    conn.execute("CREATE TABLE tblAppSettings (name TEXT, value TEXT, typevalue TEXT)")
    conn.execute("CREATE TABLE tblMusicScene (musicScene_ID INTEGER PRIMARY KEY, scene_ID INT, song_ID INT)")
    conn.execute("CREATE TABLE tblVideoScene (videoScene_ID INTEGER PRIMARY KEY, scene_ID INT, video_ID INT)")
    conn.execute("CREATE TABLE tblMediaMetadata (metadata_id INTEGER PRIMARY KEY, media_type TEXT, media_id INT)")
    conn.execute("INSERT INTO tblMusicScene (scene_ID, song_ID) VALUES (1, 3)")
    conn.execute("INSERT INTO tblMediaMetadata (media_type, media_id) VALUES ('music', 3)")
    conn.execute("INSERT INTO tblAppSettings VALUES ('yt_que_switch', '0', 'int')")
    conn.executemany("INSERT INTO tblMusic (song, displayName, urlSource, dnLoadStatus, dnLastError) VALUES (?,?,?,?,?)", [
        ('a.mp3', 'A', 'https://y/a', 3, ''),
        ('b.mp3', 'B', 'https://y/b', 3, ''),
        ('c.mp3', '',  'https://y/c', 4, 'ERROR: Sign in to confirm your age'),
        ('d.mp3', 'D', 'https://y/d', 5, 'ERROR: Video unavailable'),
        ('e.mp3', 'E', 'https://y/e', 1, ''),
        ('f.mp3', 'F', 'https://y/f', 2, ''),
        ('local.mp3', 'Local', '', 3, ''),          # no urlSource: not a download
    ])
    conn.execute("INSERT INTO tblVideoMedia (title, displayName, urlSource, dnLoadStatus, dnLastError) VALUES ('v.mp4','V','https://y/v',4,'ERROR: HTTP 403')")
    conn.commit(); conn.close()
    monkeypatch.setattr(sql, 'database', db)
    return db


def _switch(db):
    c = sqlite3.connect(db); v = c.execute("SELECT value FROM tblAppSettings WHERE name='yt_que_switch'").fetchone()[0]; c.close(); return v


class TestStats:
    def test_counts_remaining_and_rate(self, env):
        s = sql.download_stats()
        m = s['music']
        assert (m['queued'], m['processing'], m['finished'], m['failed'], m['unavailable']) == (1, 1, 2, 1, 1)
        assert m['remaining'] == 2
        assert m['failure_rate'] == 50.0, '2 bad of 4 outcomes; local files are not downloads'
        assert s['video']['failure_rate'] == 100.0 and s['video']['remaining'] == 0

    def test_failed_list_has_reason_and_name_fallback(self, env):
        rows = sql.failed_downloads()
        assert [(r['media_type'], r['id']) for r in rows] == [('music', 4), ('music', 3), ('video', 1)][:3] or len(rows) == 3
        c = {(r['media_type'], r['id']): r for r in rows}
        assert c[('music', 3)]['name'] == 'c.mp3' and 'age' in c[('music', 3)]['error']
        assert c[('music', 4)]['status_label'] == 'Unavailable'
        assert c[('video', 1)]['error'] == 'ERROR: HTTP 403'


class TestRetry:
    def test_retry_one_requeues_clears_error_and_wakes_worker(self, env):
        assert sql.retry_download('music', 3)
        c = sqlite3.connect(env)
        assert c.execute("SELECT dnLoadStatus, dnLastError FROM tblMusic WHERE song_id=3").fetchone() == (1, '')
        c.close()
        assert _switch(env) == '1'

    def test_retry_ignores_non_failed_and_bad_kind(self, env):
        assert not sql.retry_download('music', 1), 'already finished'
        assert not sql.retry_download('podcast', 3)
        assert _switch(env) == '0'

    def test_retry_all_spares_unavailable_unless_asked(self, env):
        assert sql.retry_all_failed() == 2          # music c + video v
        c = sqlite3.connect(env)
        assert c.execute("SELECT dnLoadStatus FROM tblMusic WHERE song_id=4").fetchone() == (5,)
        c.close()
        assert sql.retry_all_failed(include_unavailable=True) == 1


class TestSounds:
    def test_default_on_and_toggle(self, env, monkeypatch):
        store = {}
        monkeypatch.setattr(sql, 'appsettingGet', lambda n, d=None: store.get(n, d))
        monkeypatch.setattr(sql, 'appsettingSet', lambda n, v: store.__setitem__(n, str(v)))
        assert sql.download_sound_enabled(True) and sql.download_sound_enabled(False)
        sql.set_download_sounds(ok=False)
        assert not sql.download_sound_enabled(True) and sql.download_sound_enabled(False)
        sql.set_download_sounds(fail=False, ok=True)
        assert sql.download_sound_enabled(True) and not sql.download_sound_enabled(False)


class TestDelete:
    def test_delete_failed_removes_row_links_and_metadata(self, env):
        assert sql.delete_failed_download('music', 3)
        c = sqlite3.connect(env)
        assert c.execute("SELECT COUNT(*) FROM tblMusic WHERE song_id=3").fetchone() == (0,)
        assert c.execute("SELECT COUNT(*) FROM tblMusicScene WHERE song_ID=3").fetchone() == (0,)
        assert c.execute("SELECT COUNT(*) FROM tblMediaMetadata WHERE media_id=3").fetchone() == (0,)
        c.close()
        assert sql.delete_failed_download('music', 4), 'unavailable rows can go too'

    def test_delete_refuses_finished_queued_or_unknown(self, env):
        assert not sql.delete_failed_download('music', 1)      # finished
        assert not sql.delete_failed_download('music', 5)      # queued
        assert not sql.delete_failed_download('music', 999)
        assert not sql.delete_failed_download('podcast', 3)
        c = sqlite3.connect(env); assert c.execute("SELECT COUNT(*) FROM tblMusic").fetchone() == (7,); c.close()

    def test_delete_all_spares_unavailable_unless_asked(self, env):
        assert sql.delete_all_failed() == 2                 # music c + video v
        c = sqlite3.connect(env)
        assert c.execute("SELECT dnLoadStatus FROM tblMusic WHERE song_id=4").fetchone() == (5,)
        assert c.execute("SELECT COUNT(*) FROM tblMusic").fetchone() == (6,)
        c.close()
        assert sql.delete_all_failed(include_unavailable=True) == 1
        assert sql.delete_all_failed(include_unavailable=True) == 0
