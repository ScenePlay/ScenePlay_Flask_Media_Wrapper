"""Derived media facets (media_facets): artist derivation ladder, kind by
duration, decade, suggest/apply against a scratch db, the DM-value guard in
meta_que's auto-fill, and the playlist-origin stamp."""
import json
import sqlite3

import pytest

import media_facets as mf
import sql


class TestDerive:
    def test_topic_artist_is_exact(self):
        assert mf.derive_artist('Latte Rhythms', 'Coffee Shop Jazz Relax - Topic', {'artist': 'Coffee Shop Jazz Relax'}) == \
            ('Coffee Shop Jazz Relax', 'topic', 'exact')

    def test_title_with_channel_agreement_is_high(self):
        assert mf.derive_artist("Bon Jovi - Livin' On A Prayer (Official Music Video)", 'Bon Jovi') == ("Bon Jovi", 'title+channel', 'high')
        assert mf.derive_artist('AC/DC - Thunderstruck (Official Video)', 'acdcVEVO') == ('AC/DC', 'title+channel', 'high')

    def test_reversed_title_prefers_channel_side(self):
        assert mf.derive_artist('Blue in Green - Miles Davis', 'Miles Davis')[0] == 'Miles Davis'

    def test_title_alone_is_medium_and_channel_is_low(self):
        assert mf.derive_artist('Pink Floyd - Another Brick In The Wall (HQ)', 'mongchilde') == ('Pink Floyd', 'title', 'medium')
        assert mf.derive_artist('Take on Me', 'a-ha') == ('a-ha', 'channel', 'low')
        assert mf.derive_artist('Take on Me', 'Cool Vibes - Topic') == ('', '', 'none')

    def test_kind_and_decade(self):
        assert [mf.media_kind(d) for d in (None, 0, 200, 8 * 60, 31 * 60)] == ['', '', 'song', 'long', 'mix']
        assert mf.decade({'release_year': 1984}) == '1980s'
        assert mf.decade({}, 'Journey - Faithfully (Official HD Video - 1983)') == '1980s'
        assert mf.decade({}, 'Take on Me') == ''


@pytest.fixture
def env(tmp_path, monkeypatch):
    db = str(tmp_path / 'f.db')
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE tblMusic (song_id INTEGER PRIMARY KEY, song TEXT, displayName TEXT)")
    c.execute("CREATE TABLE tblVideoMedia (video_ID INTEGER PRIMARY KEY, title TEXT, displayName TEXT)")
    c.execute("CREATE TABLE tblMediaMetadata (metadata_id INTEGER PRIMARY KEY, media_type TEXT, media_id INT, title TEXT, "
              "uploader TEXT, duration INT, raw_json TEXT, artist TEXT DEFAULT '', artist_source TEXT DEFAULT '', "
              "origin_playlist TEXT DEFAULT '', origin_playlist_title TEXT DEFAULT '')")
    c.executemany("INSERT INTO tblMusic VALUES (?,?,?)", [(1, 'a.mp3', ''), (2, 'b.mp3', 'Take on Me'), (3, 'c.mp3', '')])
    c.executemany("INSERT INTO tblMediaMetadata (media_type, media_id, title, uploader, duration, raw_json, artist, artist_source) VALUES (?,?,?,?,?,?,?,?)", [
        ('music', 1, "Bon Jovi - Livin' On A Prayer", 'Bon Jovi', 250, '{}', '', ''),
        ('music', 2, 'Take on Me', 'a-ha', 225, '{}', '', ''),
        ('music', 3, 'Set already', 'x', 100, '{}', 'Someone', 'dm'),
    ])
    c.commit(); c.close()
    monkeypatch.setattr(sql, 'database', db)
    return db


class TestSuggestApply:
    def test_suggest_only_unset_with_ladder(self, env):
        rows = {(r['media_type'], r['id']): r for r in mf.suggest_artists(env)}
        assert ('music', 3) not in rows
        assert rows[('music', 1)]['artist'] == 'Bon Jovi' and rows[('music', 1)]['confidence'] == 'high' and rows[('music', 1)]['kind'] == 'song'
        assert rows[('music', 2)]['confidence'] == 'low'

    def test_apply_writes_dm_source_and_clears(self, env):
        assert mf.apply_artists(env, [{'media_type': 'music', 'id': 1, 'artist': 'Bon Jovi'},
                                      {'media_type': 'music', 'id': 3, 'artist': ''},
                                      {'media_type': 'podcast', 'id': 1, 'artist': 'x'}]) == 2
        c = sqlite3.connect(env)
        assert c.execute("SELECT artist, artist_source FROM tblMediaMetadata WHERE media_id=1").fetchone() == ('Bon Jovi', 'dm')
        assert c.execute("SELECT artist, artist_source FROM tblMediaMetadata WHERE media_id=3").fetchone() == ('', '')
        c.close()
        assert sql.media_artist_source('music', 1) == 'dm'


class TestOrigin:
    def test_first_origin_sticks_and_stub_row_created(self, env):
        assert sql.set_media_origin('music', 2, 'https://yt/list=A', 'Road Trip')
        assert not sql.set_media_origin('music', 2, 'https://yt/list=B', 'Other'), 'first playlist wins'
        assert sql.set_media_origin('video', 9, 'https://yt/list=C', 'Clips'), 'no metadata yet: stub row'
        c = sqlite3.connect(env)
        assert c.execute("SELECT origin_playlist_title FROM tblMediaMetadata WHERE media_type='music' AND media_id=2").fetchone() == ('Road Trip',)
        assert c.execute("SELECT origin_playlist FROM tblMediaMetadata WHERE media_type='video' AND media_id=9").fetchone() == ('https://yt/list=C',)
        c.close()
