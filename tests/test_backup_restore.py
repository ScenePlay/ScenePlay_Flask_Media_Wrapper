"""Backup / restore round-trip tests on scratch databases.

sql.database, BACKUP_DIR and UPLOADS_DIR are all pointed at tmp_path, so
create/restore/merge run for real — archives, sqlite snapshot API, ATTACH
merge — without touching the live app state.
"""

import os
import sqlite3
import zipfile

import pytest

import sql
import backup_restore as br


SCHEMA = [
    "CREATE TABLE tblMusic (song_id INTEGER PRIMARY KEY, path TEXT, song TEXT, pTimes INT, playedDTTM TEXT, active INT, genre INT, que INT, urlSource TEXT, dnLoadStatus INT, videoId TEXT, displayName TEXT, metaStatus INT DEFAULT 0, metaNextRetry TEXT)",
    "CREATE TABLE tblVideoMedia (video_id INTEGER PRIMARY KEY, path TEXT, title TEXT, pTimes INT, playedDTTM TEXT, active INT, genre INT, que INT, urlSource TEXT, dnLoadStatus INT, videoId TEXT, displayName TEXT, metaStatus INT DEFAULT 0, metaNextRetry TEXT)",
    "CREATE TABLE tblMediaMetadata (metadata_id INTEGER PRIMARY KEY, media_type TEXT, media_id INT, title TEXT, duration INT, uploader TEXT, upload_date TEXT, thumbnail TEXT, view_count INT, description TEXT, categories TEXT, raw_json TEXT, retry_count INT DEFAULT 0, last_error TEXT, extracted_at TEXT, active INT DEFAULT 1)",
    "CREATE TABLE tblScenes (scene_ID INTEGER PRIMARY KEY, sceneName TEXT, active INT, orderBy INT, campaign_id INT)",
    "CREATE TABLE tblCampaigns (campaign_id INTEGER PRIMARY KEY, campaign_name TEXT, active INT, order_by TEXT)",
    "CREATE TABLE lutGenre (genre_id INTEGER PRIMARY KEY, genre TEXT, directory TEXT, active INT, orderBy INT)",
    "CREATE TABLE tblMusicScene (musicScene_ID INTEGER PRIMARY KEY, scene_ID INT, song_ID INT, orderBy INT, volume INT)",
    "CREATE TABLE tblVideoScene (videoScene_ID INTEGER PRIMARY KEY, scene_ID INT, video_ID INT, DisplayScreen_ID INT, orderBy INT, volume INT, loops INT)",
    "CREATE TABLE tblAppSettings (name TEXT, value TEXT, typevalue TEXT)",
    "CREATE TABLE tblSubclassesLibrary (subclass_lib_id INTEGER PRIMARY KEY, api_index TEXT, name TEXT, class_name TEXT, flavor TEXT, description TEXT, source TEXT, created_at TEXT)",
    "CREATE TABLE tblFeaturesLibrary (feature_lib_id INTEGER PRIMARY KEY, api_index TEXT, name TEXT, class_name TEXT, subclass_name TEXT, level INT, prerequisites TEXT, description TEXT, source TEXT, created_at TEXT)",
    "CREATE TABLE tblMonsterTemplates (template_id INTEGER PRIMARY KEY, api_index TEXT, name TEXT, cr TEXT, monster_type TEXT, size TEXT, hp_max INT, ac INT, source TEXT, stats_json TEXT, created_at TEXT)",
]


def make_db(path):
    conn = sqlite3.connect(path)
    for stmt in SCHEMA:
        conn.execute(stmt)
    conn.commit()
    conn.close()


def q(path, sql_text, args=()):
    conn = sqlite3.connect(path)
    rows = conn.execute(sql_text, args).fetchall()
    conn.close()
    return rows


def x(path, sql_text, args=()):
    conn = sqlite3.connect(path)
    conn.execute(sql_text, args)
    conn.commit()
    conn.close()


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Scratch live-db + backup dir + uploads dir."""
    live = str(tmp_path / 'live.db')
    make_db(live)
    backups = tmp_path / 'backups'
    uploads = tmp_path / 'uploads'
    uploads.mkdir()
    (uploads / 'portraits').mkdir()
    (uploads / 'portraits' / 'hero.png').write_bytes(b'PNGDATA')
    monkeypatch.setattr(sql, 'database', live)
    monkeypatch.setattr(br, 'BACKUP_DIR', str(backups))
    monkeypatch.setattr(br, 'UPLOADS_DIR', str(uploads))
    return {'live': live, 'backups': backups, 'uploads': uploads, 'tmp': tmp_path}


class TestCreateAndList:
    def test_archive_contents(self, env):
        x(env['live'], "INSERT INTO tblScenes(sceneName, active, orderBy) VALUES ('Tavern', 1, 0)")
        path = br.create_backup(label='manual')
        assert os.path.exists(path)
        with zipfile.ZipFile(path) as z:
            names = set(z.namelist())
        assert 'manifest.json' in names and 'ScenePlay.db' in names
        assert 'uploads/portraits/hero.png' in names
        listed = br.list_backups()
        assert len(listed) == 1 and listed[0]['name'] == os.path.basename(path)

    def test_prune_only_touches_auto(self, env):
        os.makedirs(env['backups'], exist_ok=True)
        for i in range(5):
            (env['backups'] / f'sceneplay-auto-2026010{i}-000000.zip').write_bytes(b'x')
        (env['backups'] / 'sceneplay-manual-20260101-000000.zip').write_bytes(b'x')
        removed = br.prune_backups(keep=2)
        assert removed == 3
        left = sorted(os.listdir(env['backups']))
        assert 'sceneplay-manual-20260101-000000.zip' in left
        assert len([f for f in left if f.startswith('sceneplay-auto-')]) == 2

    def test_reject_non_backup_zip(self, env):
        bogus = env['tmp'] / 'bogus.zip'
        with zipfile.ZipFile(bogus, 'w') as z:
            z.writestr('hello.txt', 'nope')
        with pytest.raises(ValueError):
            br.restore_merge(str(bogus))


class TestReplace:
    def test_round_trip_and_requeue(self, env):
        # original state: one downloaded song whose file will be MISSING later
        x(env['live'],
          "INSERT INTO tblMusic(path, song, urlSource, dnLoadStatus, videoId, displayName) "
          "VALUES ('/old/home/Music/SP/', 'abc12345678.mp3', 'https://u', 3, 'abc12345678', 'My Song')")
        snap = br.create_backup(label='manual')

        # mutate: lose the row entirely
        x(env['live'], "DELETE FROM tblMusic")
        assert q(env['live'], "SELECT COUNT(*) FROM tblMusic")[0][0] == 0

        summary = br.restore_replace(snap)
        rows = q(env['live'], "SELECT song, dnLoadStatus, path FROM tblMusic")
        assert len(rows) == 1
        song, status, path = rows[0]
        assert song == 'abc12345678.mp3'
        assert status == 1                    # file absent on this box -> re-queued
        assert path.endswith('/Music/SP/')    # rewritten to THIS machine's home
        assert summary['requeued_downloads'] == 1
        # a safety snapshot of the pre-restore state was taken
        assert any(f.startswith('sceneplay-pre-restore-') for f in os.listdir(env['backups']))

    def test_uploads_restored(self, env):
        snap = br.create_backup(label='manual')
        os.remove(env['uploads'] / 'portraits' / 'hero.png')
        br.restore_replace(snap)
        assert (env['uploads'] / 'portraits' / 'hero.png').read_bytes() == b'PNGDATA'


class TestMerge:
    def _source_archive(self, env):
        """Archive of a SOURCE server: 1 campaign, 1 scene, 2 songs (one shared
        with the target), 1 video, links, metadata for one song, 1 legacy row."""
        src = str(env['tmp'] / 'source.db')
        make_db(src)
        x(src, "INSERT INTO lutGenre(genre, directory, active, orderBy) VALUES ('Battle', '', 1, 0)")
        x(src, "INSERT INTO tblCampaigns(campaign_name, active, order_by) VALUES ('Curse of Strahd', 1, '1')")
        x(src, "INSERT INTO tblScenes(sceneName, active, orderBy, campaign_id) VALUES ('Castle Fight', 1, 0, 1)")
        x(src, "INSERT INTO tblMusic(path, song, genre, urlSource, dnLoadStatus, videoId, displayName, metaStatus) "
               "VALUES ('/src/', 'shared000001.mp3', 1, 'https://u1', 3, 'shared000001', 'Shared Song', 3)")
        x(src, "INSERT INTO tblMusic(path, song, genre, urlSource, dnLoadStatus, videoId, displayName, metaStatus) "
               "VALUES ('/src/', 'newsong00001.mp3', 1, 'https://u2', 3, 'newsong00001', 'New Song', 3)")
        x(src, "INSERT INTO tblMediaMetadata(media_type, media_id, title, duration, uploader) "
               "VALUES ('music', 2, 'New Song', 200, 'Someone')")
        x(src, "INSERT INTO tblMusic(path, song, urlSource, dnLoadStatus) VALUES ('/src/', 'legacy.mp3', '', 3)")
        x(src, "INSERT INTO tblVideoMedia(path, title, urlSource, dnLoadStatus, videoId, displayName) "
               "VALUES ('/src/', 'vid000000001.mp4', 'https://u3', 3, 'vid000000001', 'A Video')")
        x(src, "INSERT INTO tblMusicScene(scene_ID, song_ID, orderBy, volume) VALUES (1, 1, 1, 80)")
        x(src, "INSERT INTO tblMusicScene(scene_ID, song_ID, orderBy, volume) VALUES (1, 2, 2, 90)")
        x(src, "INSERT INTO tblVideoScene(scene_ID, video_ID, DisplayScreen_ID, orderBy, volume, loops) "
               "VALUES (1, 1, 0, 1, 100, 0)")
        # archive it by temporarily pointing the module at the source db
        old = sql.database
        sql.database = src
        try:
            return br.create_backup(label='share')
        finally:
            sql.database = old

    def test_merge_dedups_and_links(self, env, monkeypatch):
        # target already knows the shared song (different pk) and has genre 'battle'
        x(env['live'], "INSERT INTO lutGenre(genre, directory, active, orderBy) VALUES ('battle', '', 1, 0)")
        x(env['live'], "INSERT INTO tblMusic(path, song, genre, urlSource, dnLoadStatus, videoId, displayName, metaStatus) "
                       "VALUES ('/tgt/', 'shared000001.mp3', 1, 'https://u1', 3, 'shared000001', 'Shared Song', 3)")
        archive = self._source_archive(env)

        s = br.restore_merge(archive)
        assert s['campaigns'] == 1 and s['scenes'] == 1
        assert s['music'] == 1                # only the NEW song; shared deduped
        assert s['video'] == 1
        assert s['skipped_legacy'] == 1
        assert s['links'] == 3

        # no duplicate media row for the shared videoId
        assert q(env['live'], "SELECT COUNT(*) FROM tblMusic WHERE videoId='shared000001'")[0][0] == 1
        # genre matched case-insensitively — no second 'battle' row
        assert q(env['live'], "SELECT COUNT(*) FROM lutGenre")[0][0] == 1
        # new song: queued for download, metadata copied so no re-fetch needed
        row = q(env['live'], "SELECT dnLoadStatus, metaStatus FROM tblMusic WHERE videoId='newsong00001'")[0]
        assert row == (1, 3)
        assert q(env['live'], "SELECT title FROM tblMediaMetadata WHERE media_type='music'")[0][0] == 'New Song'
        # links point at the TARGET's pks
        scene = q(env['live'], "SELECT scene_ID FROM tblScenes WHERE sceneName='Castle Fight'")[0][0]
        linked = {r[0] for r in q(env['live'],
                  "SELECT song_ID FROM tblMusicScene WHERE scene_ID = ?", (scene,))}
        shared_pk = q(env['live'], "SELECT song_id FROM tblMusic WHERE videoId='shared000001'")[0][0]
        new_pk = q(env['live'], "SELECT song_id FROM tblMusic WHERE videoId='newsong00001'")[0][0]
        assert linked == {shared_pk, new_pk}

    def test_merge_is_idempotent(self, env):
        archive = self._source_archive(env)
        br.restore_merge(archive)
        s2 = br.restore_merge(archive)
        assert (s2['campaigns'], s2['scenes'], s2['music'], s2['video'], s2['links']) == (0, 0, 0, 0, 0)


class TestMergeHomebrew:
    def _archive_with_homebrew(self, env):
        """Source server: a homebrew subclass + its feature + a homebrew
        monster, PLUS an SRD subclass that must stay behind."""
        src = str(env['tmp'] / 'brew.db')
        make_db(src)
        x(src, "INSERT INTO tblSubclassesLibrary(api_index, name, class_name, flavor, description, source, created_at) "
               "VALUES (NULL, 'Way of the Storm', 'Monk', 'Monastic Tradition', 'zap', 'homebrew', '2026-01-01')")
        x(src, "INSERT INTO tblSubclassesLibrary(api_index, name, class_name, flavor, description, source, created_at) "
               "VALUES ('open-hand', 'Open Hand', 'Monk', 'Monastic Tradition', 'srd text', 'srd', '2026-01-01')")
        x(src, "INSERT INTO tblFeaturesLibrary(api_index, name, class_name, subclass_name, level, prerequisites, description, source, created_at) "
               "VALUES (NULL, 'Storm Strike', 'Monk', 'Way of the Storm', 3, '', 'boom', 'homebrew', '2026-01-01')")
        x(src, "INSERT INTO tblMonsterTemplates(api_index, name, cr, monster_type, size, hp_max, ac, source, stats_json, created_at) "
               "VALUES (NULL, 'Frost Golem', '5', 'construct', 'Large', 90, 15, 'homebrew', '{}', '2026-01-01')")
        old = sql.database
        sql.database = src
        try:
            return br.create_backup(label='brew')
        finally:
            sql.database = old

    def test_homebrew_merges_srd_does_not(self, env):
        archive = self._archive_with_homebrew(env)
        s = br.restore_merge(archive)
        assert s['homebrew'] == 3
        assert q(env['live'], "SELECT source FROM tblSubclassesLibrary WHERE name='Way of the Storm'")[0][0] == 'homebrew'
        assert q(env['live'], "SELECT level FROM tblFeaturesLibrary WHERE name='Storm Strike'")[0][0] == 3
        assert q(env['live'], "SELECT hp_max FROM tblMonsterTemplates WHERE name='Frost Golem'")[0][0] == 90
        # SRD subclass stays behind — each box re-syncs those itself
        assert q(env['live'], "SELECT COUNT(*) FROM tblSubclassesLibrary WHERE name='Open Hand'")[0][0] == 0

    def test_homebrew_merge_dedups_by_name(self, env):
        x(env['live'], "INSERT INTO tblSubclassesLibrary(api_index, name, class_name, flavor, description, source, created_at) "
                       "VALUES (NULL, 'way of the storm', 'Monk', '', 'mine, edited', 'homebrew', '2025-01-01')")
        archive = self._archive_with_homebrew(env)
        s = br.restore_merge(archive)
        assert s['homebrew'] == 2            # subclass deduped (case-insensitive); feature + monster copied
        assert q(env['live'], "SELECT COUNT(*) FROM tblSubclassesLibrary")[0][0] == 1
        assert q(env['live'], "SELECT description FROM tblSubclassesLibrary")[0][0] == 'mine, edited'  # local wins

    def test_homebrew_merge_idempotent_and_tolerates_missing_tables(self, env):
        archive = self._archive_with_homebrew(env)
        assert br.restore_merge(archive)['homebrew'] == 3
        assert br.restore_merge(archive)['homebrew'] == 0
        # archive from an OLDER version without library tables merges cleanly
        old_src = str(env['tmp'] / 'old.db')
        conn = sqlite3.connect(old_src)
        for stmt in SCHEMA:
            if 'Library' in stmt or 'MonsterTemplates' in stmt:
                continue
            conn.execute(stmt)
        conn.commit(); conn.close()
        old = sql.database
        sql.database = old_src
        try:
            old_archive = br.create_backup(label='old-version')
        finally:
            sql.database = old
        assert br.restore_merge(old_archive)['homebrew'] == 0
