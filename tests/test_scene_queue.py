"""Scenes table "Queue" checkbox (sql.queue_scene_songs / scene_queue_state):
adds a scene's finished songs and videos to the play queue without touching
the current scene, reports all/some/none, and can pull them out again."""
import sqlite3

import pytest

import sql


@pytest.fixture
def env(tmp_path, monkeypatch):
    db = str(tmp_path / 'q.db')
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE tblMusic (song_id INTEGER PRIMARY KEY, song TEXT, que INT, dnLoadStatus INT)")
    c.execute("CREATE TABLE tblVideoMedia (video_ID INTEGER PRIMARY KEY, title TEXT, que INT, dnLoadStatus INT)")
    c.execute("CREATE TABLE tblMusicScene (musicScene_ID INTEGER PRIMARY KEY, scene_ID INT, song_ID INT)")
    c.execute("CREATE TABLE tblVideoScene (videoScene_ID INTEGER PRIMARY KEY, scene_ID INT, video_ID INT)")
    c.execute("CREATE TABLE tblAppSettings (name TEXT, value TEXT, typevalue TEXT)")
    c.executemany("INSERT INTO tblAppSettings VALUES (?, '0', 'int')", [('playsongswitch',), ('playvideoswitch',)])
    c.executemany("INSERT INTO tblMusic VALUES (?,?,?,?)", [(1, 'a', 0, 3), (2, 'b', 0, 3), (3, 'c', 0, 1), (4, 'other', 1, 3)])
    c.executemany("INSERT INTO tblVideoMedia VALUES (?,?,?,?)", [(1, 'v', 0, 3)])
    c.executemany("INSERT INTO tblMusicScene (scene_ID, song_ID) VALUES (?,?)", [(7, 1), (7, 2), (7, 3), (8, 4)])
    c.execute("INSERT INTO tblVideoScene (scene_ID, video_ID) VALUES (7, 1)")
    c.commit(); c.close()
    monkeypatch.setattr(sql, 'database', db)
    return db


def _que(db):
    c = sqlite3.connect(db)
    m = dict(c.execute("SELECT song_id, que FROM tblMusic")); v = dict(c.execute("SELECT video_ID, que FROM tblVideoMedia"))
    f = dict(c.execute("SELECT name, value FROM tblAppSettings")); c.close(); return m, v, f


def test_queue_adds_finished_media_only_and_raises_play_flags(env):
    assert sql.scene_queue_state(7) == 'none'
    assert sql.queue_scene_songs(7, True) == {'music': 2, 'video': 1}
    m, v, f = _que(env)
    assert (m[1], m[2], m[3], m[4]) == (1, 1, 0, 1), 'queued song 3 skipped (not downloaded); other scene untouched'
    assert v[1] == 1 and f['playsongswitch'] == '1' and f['playvideoswitch'] == '1'
    assert sql.scene_queue_state(7) == 'all'


def test_partial_state_and_unqueue(env):
    sql.queue_scene_songs(7, True)
    c = sqlite3.connect(env); c.execute("UPDATE tblMusic SET que = 0 WHERE song_id = 1"); c.commit(); c.close()
    assert sql.scene_queue_state(7) == 'some'
    assert sql.queue_scene_songs(7, False) == {'music': 1, 'video': 1}
    m, v, _ = _que(env)
    assert (m[1], m[2], m[4], v[1]) == (0, 0, 1, 0), 'only this scene\'s media pulled out'
    assert sql.scene_queue_state(7) == 'none'


def test_empty_scene(env):
    assert sql.scene_queue_state(99) == ''
    assert sql.queue_scene_songs(99, True) == {'music': 0, 'video': 0}


def test_queue_states_for_home_poll(env):
    assert sql.scene_queue_states() == {7: 'none', 8: 'all'}
    sql.queue_scene_songs(7, True)
    c = sqlite3.connect(env); c.execute("UPDATE tblMusic SET que = 0 WHERE song_id = 2"); c.commit(); c.close()
    assert sql.scene_queue_states() == {7: 'some', 8: 'all'}


def test_scene_delete_cascades(env):
    """Deleting a scene takes its links, pattern rows and smart rule with it;
    the media rows stay."""
    c = sqlite3.connect(env)
    c.execute("CREATE TABLE tblScenes (scene_ID INTEGER PRIMARY KEY, sceneName TEXT, active INT, orderBy INT, campaign_id INT)")
    c.execute("CREATE TABLE tblScenePattern (scenePattern_ID INTEGER PRIMARY KEY, scene_ID INT)")
    c.execute("CREATE TABLE tblwledPattern (wledPattern_ID INTEGER PRIMARY KEY, scene_ID INT)")
    c.execute("CREATE TABLE tblSceneRules (rule_id INTEGER PRIMARY KEY, scene_ID INT UNIQUE, rule_json TEXT)")
    c.execute("INSERT INTO tblScenes VALUES (7, 'Gone', 1, 1, 1)"); c.execute("INSERT INTO tblScenes VALUES (8, 'Stays', 1, 2, 1)")
    c.execute("INSERT INTO tblScenePattern (scene_ID) VALUES (7)"); c.execute("INSERT INTO tblwledPattern (scene_ID) VALUES (7)")
    c.execute("INSERT INTO tblSceneRules (scene_ID, rule_json) VALUES (7, '{}')")
    c.commit(); c.close()
    sql.CRUD_tblScenes([7], 'D')
    c = sqlite3.connect(env)
    assert c.execute("SELECT COUNT(*) FROM tblScenes").fetchone() == (1,)
    assert c.execute("SELECT COUNT(*) FROM tblMusicScene WHERE scene_ID=7").fetchone() == (0,)
    assert c.execute("SELECT COUNT(*) FROM tblVideoScene WHERE scene_ID=7").fetchone() == (0,)
    assert c.execute("SELECT COUNT(*) FROM tblScenePattern").fetchone() == (0,) and c.execute("SELECT COUNT(*) FROM tblwledPattern").fetchone() == (0,)
    assert c.execute("SELECT COUNT(*) FROM tblSceneRules").fetchone() == (0,)
    assert c.execute("SELECT COUNT(*) FROM tblMusicScene WHERE scene_ID=8").fetchone() == (1,), 'other scene untouched'
    assert c.execute("SELECT COUNT(*) FROM tblMusic").fetchone() == (4,), 'media rows kept'
    c.close()


def test_set_scene_order(env):
    c = sqlite3.connect(env)
    c.execute("CREATE TABLE tblScenes (scene_ID INTEGER PRIMARY KEY, sceneName TEXT, active INT, orderBy INT, campaign_id INT)")
    c.executemany("INSERT INTO tblScenes VALUES (?,?,1,?,1)", [(1, 'a', 1), (2, 'b', 2), (3, 'c', 3), (9, 'other', 40)])
    c.commit(); c.close()
    assert sql.set_scene_order([3, 'x', 1, 2]) == 3
    c = sqlite3.connect(env)
    assert c.execute("SELECT scene_ID, orderBy FROM tblScenes ORDER BY scene_ID").fetchall() == [(1, 2), (2, 3), (3, 1), (9, 40)]
    c.close()
