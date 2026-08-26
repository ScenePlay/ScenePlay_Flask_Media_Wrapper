"""Organize Library (library_organize): plan reports without writing; run
labels genres (scene-based by default) and artists (exact/high by default),
creates or attaches smart scenes, refreshes; options widen each step."""
import json
import sqlite3

import pytest

import library_organize as lo


@pytest.fixture
def env(tmp_path):
    db = str(tmp_path / 'o.db')
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE lutGenre (genre_id INTEGER PRIMARY KEY, genre TEXT, directory TEXT, active INT, orderBY INT)")
    c.execute("CREATE TABLE tblMusic (song_id INTEGER PRIMARY KEY, song TEXT, displayName TEXT, genre INT, active INT DEFAULT 1)")
    c.execute("CREATE TABLE tblVideoMedia (video_ID INTEGER PRIMARY KEY, title TEXT, displayName TEXT, genre INT, active INT DEFAULT 1)")
    c.execute("CREATE TABLE tblMediaMetadata (metadata_id INTEGER PRIMARY KEY, media_type TEXT, media_id INT, title TEXT, uploader TEXT, description TEXT, duration INT, raw_json TEXT, artist TEXT DEFAULT '', artist_source TEXT DEFAULT '')")
    c.execute("CREATE TABLE tblCampaigns (campaign_id INTEGER PRIMARY KEY, campaign_name TEXT)")
    c.execute("CREATE TABLE tblScenes (scene_ID INTEGER PRIMARY KEY, sceneName TEXT, active INT, orderBy INT, campaign_id INT)")
    c.execute("CREATE TABLE tblMusicScene (musicScene_ID INTEGER PRIMARY KEY, scene_ID INT, song_ID INT, orderBy INT, volume INT, loops INT)")
    c.execute("CREATE TABLE tblVideoScene (videoScene_ID INTEGER PRIMARY KEY, scene_ID INT, video_ID INT, DisplayScreen_ID INT, orderBy INT, volume INT, loops INT)")
    c.execute("INSERT INTO lutGenre VALUES (1, 'Rock', '', 1, 1)")
    c.execute("INSERT INTO tblCampaigns VALUES (1, 'Music')")
    c.executemany("INSERT INTO tblScenes VALUES (?,?,?,?,?)", [(1, 'Rock', 1, 1, 1), (2, 'Jazz', 1, 2, 1)])
    songs = [(1, 'AC/DC - Thunderstruck (Official Video)', 'acdcVEVO', 1, ['rock']),
             (2, 'AC/DC - Back in Black', 'acdcVEVO', 1, ['rock']),
             (3, 'Miles Davis - So What', 'jazzfan', 2, ['jazz']),
             (4, 'Blue in Green', 'Miles Davis - Topic', 2, ['jazz']),
             (5, 'Lonely tune', 'somebody', None, ['pop'])]
    for sid, title, chan, scene, tags in songs:
        c.execute("INSERT INTO tblMusic (song_id, song, displayName, genre) VALUES (?,?,?,0)", (sid, f'{sid}.mp3', ''))
        info = {'tags': tags}
        if 'Topic' in chan:
            info['artist'] = 'Miles Davis'
        c.execute("INSERT INTO tblMediaMetadata (media_type, media_id, title, uploader, description, duration, raw_json) VALUES ('music',?,?,?,?,?,?)",
                  (sid, title, chan, '', 200, json.dumps(info)))
        if scene:
            c.execute("INSERT INTO tblMusicScene (scene_ID, song_ID, orderBy, volume, loops) VALUES (?,?,1,100,0)", (scene, sid))
    c.commit(); c.close()
    store = {}
    return db, (lambda n, d=None: store.get(n, d))


def _q(db, sql):
    c = sqlite3.connect(db); r = c.execute(sql).fetchall(); c.close(); return r


class TestPlan:
    def test_plan_writes_nothing(self, env):
        db, get = env
        p = lo.plan(db, get, {'artist_min': 2, 'genre_min': 2})
        assert p['genres']['apply'] == 4 and p['genres']['names'] == ['Jazz', 'Rock']
        assert p['artists']['apply'] == 3          # 2 high (AC/DC) + 1 exact (Topic); song 3 is medium
        # no artist is set yet → no artist scenes; genres are DERIVED from the
        # tags on the fly (smart_scenes.derived_genre), so genre scenes appear
        # even before labels are written — still nothing is written by plan()
        assert p['scenes']['artists'] == []
        assert sorted(g['name'] for g in p['scenes']['genres']) == ['Jazz', 'Rock']
        assert _q(db, "SELECT COUNT(*) FROM tblMusic WHERE genre <> 0") == [(0,)]
        assert _q(db, "SELECT COUNT(*) FROM tblScenes") == [(2,)]


class TestRun:
    def test_run_default_is_conservative_and_attaches_existing(self, env):
        db, get = env
        r = lo.run(db, get, {'artist_min': 2, 'genre_min': 2, 'campaign_id': 1})
        assert r['genres']['applied'] == 4 and r['genres']['created_genres'] == ['Jazz']
        assert r['artists']['applied'] == 3
        acts = {s['name']: s['action'] for s in r['scenes']['genres']}
        assert acts == {'Rock': 'attached', 'Jazz': 'attached'}, 'hand-built genre scenes become smart, not duplicated'
        assert [(s['name'], s['action']) for s in r['scenes']['artists']] == [('AC/DC', 'created')], \
            'song 3 is a medium derivation, so Miles Davis has one labelled song — under the threshold of 2'
        assert _q(db, "SELECT COUNT(*) FROM tblSceneRules") == [(3,)]
        assert _q(db, "SELECT genre FROM tblMusic WHERE song_id=5") == [(0,)], 'tag-only genre left alone by default'
        assert r['refreshed']['scenes'] == 3

    def test_wider_options(self, env):
        db, get = env
        r = lo.run(db, get, {'artist_min': 2, 'genre_min': 1, 'campaign_id': 1,
                             'genres_include_tags': True, 'artists_include_medium': True})
        assert _q(db, "SELECT g.genre FROM tblMusic m JOIN lutGenre g ON g.genre_id=m.genre WHERE song_id=5") == [('Pop',)]
        assert r['artists']['applied'] == 4
        assert _q(db, "SELECT COUNT(*) FROM tblMusicScene ms JOIN tblScenes s ON s.scene_ID=ms.scene_ID WHERE s.sceneName='Miles Davis'") == [(2,)]
        assert any(s['name'] == 'Pop' and s['action'] == 'created' for s in r['scenes']['genres'])

    def test_rerun_is_idempotent(self, env):
        db, get = env
        lo.run(db, get, {'artist_min': 2, 'genre_min': 2, 'campaign_id': 1})
        r2 = lo.run(db, get, {'artist_min': 2, 'genre_min': 2, 'campaign_id': 1})
        assert r2['genres']['applied'] == 0 and r2['artists']['applied'] == 0
        assert all(s['action'] == 'skipped' for s in r2['scenes']['genres'] + r2['scenes']['artists'])
        assert _q(db, "SELECT COUNT(*) FROM tblScenes") == [(3,)]
