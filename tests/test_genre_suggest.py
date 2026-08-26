"""Genre suggestions (genre_suggest): scene membership outranks tags, the
mapping is data (seed + saved JSON), conflicts are flagged not guessed, and
apply() writes only confirmed rows, creating genres by name."""
import json
import sqlite3

import pytest

import genre_suggest as gs


@pytest.fixture
def env(tmp_path):
    db = str(tmp_path / 'g.db')
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE lutGenre (genre_id INTEGER PRIMARY KEY, genre TEXT, directory TEXT, active INT, orderBY INT)")
    c.execute("CREATE TABLE tblMusic (song_id INTEGER PRIMARY KEY, song TEXT, displayName TEXT, genre INT)")
    c.execute("CREATE TABLE tblScenes (scene_ID INTEGER PRIMARY KEY, sceneName TEXT)")
    c.execute("CREATE TABLE tblMusicScene (musicScene_ID INTEGER PRIMARY KEY, scene_ID INT, song_ID INT)")
    c.execute("CREATE TABLE tblMediaMetadata (metadata_id INTEGER PRIMARY KEY, media_type TEXT, media_id INT, title TEXT, uploader TEXT, description TEXT, raw_json TEXT)")
    c.executemany("INSERT INTO lutGenre VALUES (?,?,?,?,?)", [(1, '', '', 1, 0), (2, 'Classical', '', 1, 1), (3, 'Rock', '', 1, 2)])
    c.executemany("INSERT INTO tblScenes VALUES (?,?)", [(1, 'Rock'), (2, 'Coffee Jazz'), (3, 'Classical'), (4, 'Damp Cave'), (5, 'Jazz')])
    songs = [  # id, name, genre, scenes, tags
        (1, 'Thunderstruck', 0, [1], ['official video', 'vevo']),
        (2, 'Latte Rhythms', 0, [2], ['jazz', 'coffee']),
        (3, 'Nocturne', 0, [3], ['chopin', 'piano']),
        (4, 'Cave drips', 0, [4], ['ambient', 'dungeon']),
        (5, 'Sweet Dreams', 0, [1], ['80s pop', 'synthpop']),          # scene says Rock, tags say Pop
        (6, 'Torn', 0, [1, 5], ['music']),                               # two genre scenes
        (7, 'Mystery', 0, [], []),
        (8, 'Already set', 3, [1], ['rock']),
    ]
    for sid, name, genre, scenes, tags in songs:
        c.execute("INSERT INTO tblMusic VALUES (?,?,?,?)", (sid, name + '.mp3', name, genre))
        for sc in scenes:
            c.execute("INSERT INTO tblMusicScene (scene_ID, song_ID) VALUES (?,?)", (sc, sid))
        c.execute("INSERT INTO tblMediaMetadata (media_type, media_id, title, uploader, description, raw_json) VALUES ('music',?,?,?,?,?)",
                  (sid, name, 'chan', '', json.dumps({'tags': tags})))
    c.commit(); c.close()
    store = {}
    return db, store, (lambda n, d=None: store.get(n, d))


class TestSuggest:
    def test_scene_outranks_tags_and_shows_disagreement(self, env):
        db, store, get = env
        r = {x['song_id']: x for x in gs.suggest(db, get)}
        assert 8 not in r, 'songs with a genre are left alone'
        assert r[1]['suggested'] == 'Rock' and r[1]['confidence'] == 'scene' and 'scene "Rock"' in r[1]['reason']
        assert r[2]['suggested'] == 'Jazz' and r[2]['confidence'] == 'scene', 'Coffee Jazz maps to Jazz via the seed map'
        assert r[3]['suggested'] == 'Classical', 'scene named like an existing genre needs no mapping'
        assert r[4]['suggested'] == 'Soundtrack' and r[4]['confidence'] == 'tags', 'Damp Cave is a mood, tags decide'
        assert r[5]['suggested'] == 'Rock' and r[5]['confidence'] == 'scene' and r[5]['alt'] == 'Pop', \
            'scene decides; the tag opinion rides along for the review page'
        assert r[6]['suggested'] is None and r[6]['confidence'] == 'conflict' and 'Jazz' in r[6]['reason']
        assert r[7]['suggested'] is None and r[7]['confidence'] == 'none'

    def test_saved_map_overrides_and_removes(self, env):
        db, store, get = env
        store['genre_scene_map'] = json.dumps({'Damp Cave': 'Ambient', 'coffee jazz': ''})
        r = {x['song_id']: x for x in gs.suggest(db, get)}
        assert r[4]['suggested'] == 'Ambient' and r[4]['confidence'] == 'scene'
        assert r[2]['suggested'] == 'Jazz' and r[2]['confidence'] == 'tags', 'mapping removed: tags take over'

    def test_bad_saved_map_ignored(self, env):
        db, store, get = env
        store['genre_scene_map'] = '{not json'
        assert gs.scene_map(get)['coffee jazz'] == 'Jazz'


class TestApply:
    def test_apply_creates_missing_genre_and_skips_blank(self, env):
        db, store, get = env
        out = gs.apply(db, [{'song_id': 1, 'genre': 'rock'}, {'song_id': 2, 'genre': 'Jazz'},
                            {'song_id': 3, 'genre': ''}, {'song_id': 'x', 'genre': 'Jazz'}])
        assert out['updated'] == 2 and out['created'] == ['Jazz']
        c = sqlite3.connect(db)
        assert c.execute("SELECT genre FROM tblMusic WHERE song_id=1").fetchone() == (3,), 'matched Rock case-insensitively'
        jid = c.execute("SELECT genre_id FROM lutGenre WHERE genre='Jazz'").fetchone()[0]
        assert c.execute("SELECT genre FROM tblMusic WHERE song_id=2").fetchone() == (jid,)
        assert c.execute("SELECT genre FROM tblMusic WHERE song_id=3").fetchone() == (0,)
        c.close()
        assert 'Jazz' in gs.genre_names(db)
