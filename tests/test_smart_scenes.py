"""Smart scenes (smart_scenes): rule normalisation/summary, matching across
facets, create + refresh (adds only, never removes), attach/drop on an
existing scene, auto-refresh selection, and bulk creation with dedup."""
import json
import sqlite3

import pytest

import smart_scenes as ss


@pytest.fixture
def env(tmp_path):
    db = str(tmp_path / 's.db')
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE lutGenre (genre_id INTEGER PRIMARY KEY, genre TEXT, directory TEXT, active INT, orderBY INT)")
    c.execute("CREATE TABLE tblMusic (song_id INTEGER PRIMARY KEY, song TEXT, displayName TEXT, genre INT, active INT DEFAULT 1)")
    c.execute("CREATE TABLE tblVideoMedia (video_ID INTEGER PRIMARY KEY, title TEXT, displayName TEXT, genre INT, active INT DEFAULT 1)")
    c.execute("CREATE TABLE tblMediaMetadata (metadata_id INTEGER PRIMARY KEY, media_type TEXT, media_id INT, title TEXT, uploader TEXT, description TEXT DEFAULT '', duration INT, raw_json TEXT, artist TEXT DEFAULT '')")
    c.execute("CREATE TABLE tblCampaigns (campaign_id INTEGER PRIMARY KEY, campaign_name TEXT)")
    c.execute("CREATE TABLE tblScenes (scene_ID INTEGER PRIMARY KEY, sceneName TEXT, active INT, orderBy INT, campaign_id INT)")
    c.execute("CREATE TABLE tblMusicScene (musicScene_ID INTEGER PRIMARY KEY, scene_ID INT, song_ID INT, orderBy INT, volume INT, loops INT)")
    c.execute("CREATE TABLE tblVideoScene (videoScene_ID INTEGER PRIMARY KEY, scene_ID INT, video_ID INT, DisplayScreen_ID INT, orderBy INT, volume INT, loops INT)")
    c.executemany("INSERT INTO lutGenre VALUES (?,?,?,?,?)", [(1, 'Jazz', '', 1, 1), (2, 'Rock', '', 1, 2)])
    c.execute("INSERT INTO tblCampaigns VALUES (1, 'Music')")
    songs = [(1, 'So What', 1, 'Miles Davis', 560, {'release_year': 1959}),
             (2, 'Blue in Green', 1, 'Miles Davis', 330, {'release_year': 1959}),
             (3, 'Coffee Mix 3h', 1, '', 3 * 3600, {}),
             (4, 'Thunderstruck', 2, 'AC/DC', 290, {}),
             (5, 'Back in Black', 2, 'AC/DC', 255, {'release_year': 1980})]
    for sid, name, g, artist, dur, info in songs:
        c.execute("INSERT INTO tblMusic (song_id, song, displayName, genre) VALUES (?,?,?,?)", (sid, name + '.mp3', name, g))
        c.execute("INSERT INTO tblMediaMetadata (media_type, media_id, title, uploader, duration, raw_json, artist) VALUES ('music',?,?,?,?,?,?)",
                  (sid, name, 'chan', dur, json.dumps(info), artist))
    c.execute("INSERT INTO tblVideoMedia (video_ID, title, displayName, genre) VALUES (1, 'live.mp4', 'AC/DC Live', 2)")
    c.execute("INSERT INTO tblMediaMetadata (media_type, media_id, title, uploader, duration, raw_json, artist) VALUES ('video',1,'AC/DC Live','chan',4000,'{}','AC/DC')")
    c.commit(); c.close()
    return db


def _links(db, scene_id):
    c = sqlite3.connect(db)
    m = [r[0] for r in c.execute("SELECT song_ID FROM tblMusicScene WHERE scene_ID=? ORDER BY 1", (scene_id,))]
    v = [r[0] for r in c.execute("SELECT video_ID FROM tblVideoScene WHERE scene_ID=? ORDER BY 1", (scene_id,))]
    c.close(); return m, v


class TestRules:
    def test_normalize_and_describe(self):
        r = ss.normalize({'genres': ['Jazz', ' Jazz '], 'kinds': ['mix', 'bogus'], 'media': ['music'], 'text': ' coffee '})
        assert r == {'media': ['music'], 'genres': ['Jazz'], 'artists': [], 'kinds': ['mix'], 'decades': [], 'text': 'coffee', 'scenes': [], 'combine': 'all'}
        assert ss.describe(r) == 'Jazz · Mix / ambience · "coffee" (music)'
        assert ss.describe({}) == 'everything (music + video)'

    def test_match_across_facets(self, env):
        assert sorted(i for i, _ in ss.match(env, {'genres': ['jazz']})['music']) == [1, 2, 3]
        assert [i for i, _ in ss.match(env, {'genres': ['Jazz'], 'kinds': ['mix']})['music']] == [3]
        assert [i for i, _ in ss.match(env, {'artists': ['AC/DC']})['music']] == [5, 4] or \
            sorted(i for i, _ in ss.match(env, {'artists': ['AC/DC']})['music']) == [4, 5]
        assert [i for i, _ in ss.match(env, {'artists': ['AC/DC']})['video']] == [1]
        assert sorted(i for i, _ in ss.match(env, {'decades': ['1950s']})['music']) == [1, 2]
        assert [i for i, _ in ss.match(env, {'text': 'black', 'media': ['music']})['music']] == [5]
        assert ss.match(env, {'genres': ['Rock'], 'media': ['music']})['video'] == []

    def test_facet_options(self, env):
        o = ss.facet_options(env)
        assert [g['value'] for g in o['genres']] == ['Jazz', 'Rock'] and o['genres'][1]['count'] == 3
        assert o['artists'][0] == {'value': 'AC/DC', 'count': 3}
        assert {d['value'] for d in o['decades']} == {'1950s', '1980s'}


class TestScenes:
    def test_create_fills_and_refresh_only_adds(self, env):
        res = ss.create_scene(env, 'Miles', 1, {'artists': ['Miles Davis']})
        sid = res['scene_id']
        assert res['added'] == {'music': 2, 'video': 0} and _links(env, sid)[0] == [1, 2]
        c = sqlite3.connect(env); c.execute("INSERT INTO tblMusicScene (scene_ID, song_ID, orderBy, volume, loops) VALUES (?, 4, 1, 100, 0)", (sid,))
        c.execute("DELETE FROM tblMusicScene WHERE scene_ID=? AND song_ID=2", (sid,)); c.commit(); c.close()
        assert ss.refresh(env, sid) == {'music': 1, 'video': 0}
        assert _links(env, sid)[0] == [1, 2, 4], 'hand-added song kept; removed match re-added'
        assert c is not None
        rows = ss.list_rules(env)
        assert rows[0]['name'] == 'Miles' and rows[0]['summary'] == 'Miles Davis (music + video)' and rows[0]['music'] == 3

    def test_scene_order_and_name_required(self, env):
        c = sqlite3.connect(env); c.execute("INSERT INTO tblScenes VALUES (9, 'Old', 1, 5, 1)"); c.commit(); c.close()
        sid = ss.create_scene(env, 'New', 1, {})['scene_id']
        c = sqlite3.connect(env); assert c.execute("SELECT orderBy, active FROM tblScenes WHERE scene_ID=?", (sid,)).fetchone() == (6, 1); c.close()
        with pytest.raises(ValueError):
            ss.create_scene(env, '  ', 1, {})

    def test_attach_and_drop_on_existing_scene(self, env):
        c = sqlite3.connect(env); c.execute("INSERT INTO tblScenes VALUES (7, 'Rock', 1, 1, 1)"); c.commit(); c.close()
        ss.set_rule(env, 7, {'genres': ['Rock']})
        assert ss.refresh(env, 7) == {'music': 2, 'video': 1}
        ss.drop_rule(env, 7)
        assert ss.list_rules(env) == [] and _links(env, 7) == ([4, 5], [1]), 'links survive the unlink'
        assert ss.refresh(env, 7) == {'music': 0, 'video': 0}

    def test_refresh_all_honours_auto_flag(self, env):
        a = ss.create_scene(env, 'A', 1, {'genres': ['Jazz']}, auto_refresh=True)['scene_id']
        b = ss.create_scene(env, 'B', 1, {'genres': ['Rock']}, auto_refresh=False)['scene_id']
        c = sqlite3.connect(env)
        c.execute("INSERT INTO tblMusic (song_id, song, displayName, genre) VALUES (6, 'n.mp3', 'New Jazz', 1)")
        c.execute("INSERT INTO tblMusic (song_id, song, displayName, genre) VALUES (7, 'r.mp3', 'New Rock', 2)")
        c.commit(); c.close()
        assert ss.refresh_all(env) == {a: {'music': 1, 'video': 0}}
        assert ss.refresh_all(env, auto_only=False)[b] == {'music': 1, 'video': 0}

    def test_bulk_by_artist_with_threshold_and_dedup(self, env):
        c = sqlite3.connect(env); c.execute("INSERT INTO tblScenes VALUES (3, 'AC/DC', 1, 1, 1)"); c.commit(); c.close()
        made = ss.bulk_create(env, 'artist', 2, 1)
        assert [(m['name'], m['action']) for m in made] == [('AC/DC', 'skipped'), ('Miles Davis', 'created')], \
            'AC/DC exists already (reported, not duplicated); Coffee has no artist'
        again = ss.bulk_create(env, 'artist', 2, 1)
        assert [m['action'] for m in again] == ['skipped', 'skipped'], 'idempotent'
        plan = ss.bulk_create(env, 'genre', 3, 1, media=('music',), name_format='{value} (all)', dry_run=True)
        assert [(m['name'], m['count'], m['action']) for m in plan] == [('Jazz (all)', 3, 'created')]
        assert not any(s == 'Jazz (all)' for (s,) in sqlite3.connect(env).execute("SELECT sceneName FROM tblScenes")), 'dry run wrote nothing'
        att = ss.bulk_create(env, 'artist', 2, 1, attach_existing=True)
        assert [(m['name'], m['action']) for m in att] == [('AC/DC', 'attached'), ('Miles Davis', 'skipped')]
        assert _links(env, 3)[0] == [4, 5], 'attached rule filled the hand-made AC/DC scene'
        with pytest.raises(ValueError):
            ss.bulk_create(env, 'decade', 1, 1)


class TestSceneSources:
    def test_scenes_as_source_union_and_intersection(self, env):
        c = sqlite3.connect(env)
        c.executemany("INSERT INTO tblScenes VALUES (?,?,?,?,?)", [(10, 'Jazz', 1, 1, 1), (11, 'Rock', 1, 2, 1)])
        c.executemany("INSERT INTO tblMusicScene (scene_ID, song_ID, orderBy, volume, loops) VALUES (?,?,1,100,0)",
                      [(10, 1), (10, 2), (10, 3), (11, 4), (11, 5)])
        c.execute("INSERT INTO tblVideoScene (scene_ID, video_ID, DisplayScreen_ID, orderBy, volume, loops) VALUES (11, 1, 0, 1, 100, 0)")
        c.commit(); c.close()
        union = ss.match(env, {'scenes': ['jazz', 'Rock']})
        assert sorted(i for i, _ in union['music']) == [1, 2, 3, 4, 5] and [i for i, _ in union['video']] == [1]
        assert [i for i, _ in ss.match(env, {'scenes': ['Jazz'], 'kinds': ['mix']})['music']] == [3], 'AND with other facets'
        assert ss.match(env, {'scenes': ['Nope']})['music'] == [], 'unknown scene → nothing, not everything'
        assert ss.describe({'scenes': ['Jazz', 'Rock'], 'kinds': ['mix']}) == 'from Jazz, Rock · Mix / ambience (music + video)'
        assert [o['value'] for o in ss.facet_options(env)['scenes']] == ['Jazz', 'Rock']

    def test_scene_is_never_its_own_source(self, env):
        c = sqlite3.connect(env)
        c.execute("INSERT INTO tblScenes VALUES (10, 'Jazz', 1, 1, 1)")
        c.execute("INSERT INTO tblMusicScene (scene_ID, song_ID, orderBy, volume, loops) VALUES (10, 1, 1, 100, 0)")
        c.commit(); c.close()
        ss.set_rule(env, 10, {'scenes': ['Jazz'], 'artists': ['AC/DC']})
        assert ss.refresh(env, 10) == {'music': 0, 'video': 0}, 'own members excluded as a source; nothing else in Jazz'
        assert _links(env, 10)[0] == [1]


class TestCombineAny:
    def test_union_across_categories(self, env):
        c = sqlite3.connect(env)
        c.execute("INSERT INTO tblScenes VALUES (10, 'Jazz', 1, 1, 1)")
        c.executemany("INSERT INTO tblMusicScene (scene_ID, song_ID, orderBy, volume, loops) VALUES (?,?,1,100,0)", [(10, 1), (10, 2)])
        c.commit(); c.close()
        # Jazz scene (1,2) OR artist AC/DC (4,5) OR kind mix (3) → everything
        r = {'scenes': ['Jazz'], 'artists': ['AC/DC'], 'kinds': ['mix'], 'combine': 'any'}
        assert sorted(i for i, _ in ss.match(env, r)['music']) == [1, 2, 3, 4, 5]
        assert [i for i, _ in ss.match(env, r)['video']] == [1], 'AC/DC video via the artist pick'
        # same picks, intersection → nothing satisfies all three
        assert ss.match(env, dict(r, combine='all'))['music'] == []
        assert ss.describe(r) == 'from Jazz or AC/DC or Mix / ambience (music + video)'
        assert ss.normalize({})['combine'] == 'all', 'older rules keep intersection semantics'


class TestDerivedGenre:
    def test_label_wins_else_tags(self):
        assert ss.derived_genre('Rock', 'x', 'y', '', json.dumps({'tags': ['jazz']})) == 'Rock'
        assert ss.derived_genre('', 'Blue in Green', 'chan', '', json.dumps({'tags': ['jazz', 'trumpet']})) == 'Jazz'
        assert ss.derived_genre('', 'AC/DC - Thunderstruck', 'acdc', '', json.dumps({'tags': ['official video']})) == ''
        assert ss.derived_genre('', 'AC/DC - Thunderstruck', 'acdc', 'hard rock classic', '{}') == 'Rock'

    def test_genre_facet_and_match_use_derivation(self, env):
        c = sqlite3.connect(env)
        # song 4 has no label: give it rock tags; song 1 is labelled Jazz already
        c.execute("UPDATE tblMediaMetadata SET raw_json=? WHERE media_type='music' AND media_id=4", (json.dumps({'tags': ['rock', 'live']}),))
        c.execute("UPDATE tblMusic SET genre=0 WHERE song_id IN (4, 5)")
        c.commit(); c.close()
        opts = {o['value']: o['count'] for o in ss.facet_options(env)['genres']}
        assert opts['Jazz'] == 3 and opts['Rock'] == 2, 'video (label Rock) + song 4 (tags)'
        assert sorted(i for i, _ in ss.match(env, {'genres': ['rock'], 'media': ['music']})['music']) == [4]
