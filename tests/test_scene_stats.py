"""Home scene cards: song/video counts and estimated play time
(sql.scene_media_stats / fmt_play_time)."""
import sqlite3

import pytest

import sql


@pytest.fixture
def env(tmp_path, monkeypatch):
    db = str(tmp_path / 's.db')
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE tblMusic (song_id INTEGER PRIMARY KEY, song TEXT, dnLoadStatus INT)")
    c.execute("CREATE TABLE tblVideoMedia (video_ID INTEGER PRIMARY KEY, title TEXT, dnLoadStatus INT)")
    c.execute("CREATE TABLE tblMusicScene (musicScene_ID INTEGER PRIMARY KEY, scene_ID INT, song_ID INT, loops INT)")
    c.execute("CREATE TABLE tblVideoScene (videoScene_ID INTEGER PRIMARY KEY, scene_ID INT, video_ID INT, loops INT)")
    c.execute("CREATE TABLE tblMediaMetadata (metadata_id INTEGER PRIMARY KEY, media_type TEXT, media_id INT, duration INT)")
    c.executemany("INSERT INTO tblMusic VALUES (?,?,?)", [(1, 'a', 3), (2, 'b', 3), (3, 'nometa', 3), (4, 'queued', 1)])
    c.execute("INSERT INTO tblVideoMedia VALUES (1, 'v', 3)")
    c.executemany("INSERT INTO tblMediaMetadata (media_type, media_id, duration) VALUES (?,?,?)", [('music', 1, 600), ('music', 2, 300), ('video', 1, 90)])
    c.executemany("INSERT INTO tblMusicScene (scene_ID, song_ID, loops) VALUES (?,?,?)", [(7, 1, 0), (7, 2, 2), (7, 3, 0), (7, 4, 0), (8, 1, 0)])
    c.execute("INSERT INTO tblVideoScene (scene_ID, video_ID, loops) VALUES (7, 1, 1)")
    c.commit(); c.close()
    monkeypatch.setattr(sql, 'database', db)
    return db


def test_counts_and_looped_time(env):
    st = sql.scene_media_stats()
    # scene 7: songs 1,2,3 downloaded (4 not); time = 600 + 300×3 + 0 (no metadata) + video 90×2
    assert st[7] == {'songs': 3, 'videos': 1, 'seconds': 600 + 900 + 180, 'play_time': '28m'}
    assert st[8] == {'songs': 1, 'videos': 0, 'seconds': 600, 'play_time': '10m'}
    assert 99 not in st


def test_fmt_play_time():
    assert [sql.fmt_play_time(x) for x in (0, None, 20, 200, 3 * 60 + 40, 12 * 60 + 5, 7800)] == \
        ['', '', '20s', '3m', '3m 40s', '12m', '2h 10m']
