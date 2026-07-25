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
    "CREATE TABLE tblMusicScene (musicScene_ID INTEGER PRIMARY KEY, scene_ID INT, song_ID INT, orderBy INT, volume INT, loops INT)",
    "CREATE TABLE tblVideoScene (videoScene_ID INTEGER PRIMARY KEY, scene_ID INT, video_ID INT, DisplayScreen_ID INT, orderBy INT, volume INT, loops INT)",
    "CREATE TABLE tblAppSettings (name TEXT, value TEXT, typevalue TEXT)",
    "CREATE TABLE tblSubclassesLibrary (subclass_lib_id INTEGER PRIMARY KEY, api_index TEXT, name TEXT, class_name TEXT, flavor TEXT, description TEXT, source TEXT, created_at TEXT)",
    "CREATE TABLE tblFeaturesLibrary (feature_lib_id INTEGER PRIMARY KEY, api_index TEXT, name TEXT, class_name TEXT, subclass_name TEXT, level INT, prerequisites TEXT, description TEXT, source TEXT, created_at TEXT)",
    "CREATE TABLE tblMonsterTemplates (template_id INTEGER PRIMARY KEY, api_index TEXT, name TEXT, cr TEXT, monster_type TEXT, size TEXT, hp_max INT, ac INT, source TEXT, stats_json TEXT, created_at TEXT)",
    # full-merge (TTRPG tree + lighting) tables
    "CREATE TABLE tblUsers (user_id INTEGER PRIMARY KEY, username TEXT, password_hash TEXT, display_name TEXT, role TEXT, active INT, created_at TEXT)",
    "CREATE TABLE tblCharacters (character_id INTEGER PRIMARY KEY, user_id INT NOT NULL, name TEXT, char_class TEXT, level INT, hp_current INT, hp_max INT, active INT, created_at TEXT)",
    "CREATE TABLE tblCharacterWeapons (char_weapon_id INTEGER PRIMARY KEY, character_id INT, weapon_lib_id INT, weapon_name TEXT, damage_dice TEXT, equipped INT, order_by INT)",
    "CREATE TABLE tblCharacterNotes (note_id INTEGER PRIMARY KEY, character_id INT, note_text TEXT, created_at TEXT)",
    "CREATE TABLE tblWeaponsLibrary (weapon_lib_id INTEGER PRIMARY KEY, name TEXT, source TEXT)",
    "CREATE TABLE tblSessions (session_id INTEGER PRIMARY KEY, title TEXT, session_number INT, campaign_id INT, status TEXT, dm_notes TEXT, session_date TEXT, created_at TEXT)",
    "CREATE TABLE tblSessionParty (sp_id INTEGER PRIMARY KEY, session_id INT, character_id INT, is_active INT, joined_at TEXT)",
    "CREATE TABLE tblSessionMonsters (monster_id INTEGER PRIMARY KEY, session_id INT, template_id INT, display_name TEXT, hp_current INT, hp_max INT, ac INT, initiative INT, conditions TEXT, is_alive INT, sort_order INT)",
    "CREATE TABLE tblSessionNotes (note_id INTEGER PRIMARY KEY, session_id INT, title TEXT, body TEXT, sort_order INT, created_at TEXT, updated_at TEXT)",
    "CREATE TABLE tblBattleMaps (map_id INTEGER PRIMARY KEY, session_id INT, name TEXT, grid_cols INT, grid_rows INT, bg_image TEXT, is_active INT, movement_scale REAL, sort_order INT, created_at TEXT)",
    "CREATE TABLE tblBattleMapTokens (token_id INTEGER PRIMARY KEY, map_id INT, entity_type TEXT, entity_id INT, col INT, row INT, updated_at TEXT)",
    "CREATE TABLE tblBattleMapEffects (effect_id INTEGER PRIMARY KEY, map_id INT, shape TEXT, label TEXT, anchor_x REAL, anchor_y REAL, size_ft INT, angle REAL, fill_color TEXT, fill_opacity REAL, border_color TEXT, created_at TEXT)",
    "CREATE TABLE tblBattleMapNotes (note_id INTEGER PRIMARY KEY, map_id INT, title TEXT, body TEXT, sort_order INT, created_at TEXT, updated_at TEXT)",
    "CREATE TABLE tblScenePattern (scenePattern_ID INTEGER PRIMARY KEY, scene_ID INT, ledTypeModel_ID INT, color TEXT, wait_ms INT, iterations INT, direction INT, cdiff INT, orderBy INT, outPin INT, brightness INT)",
    "CREATE TABLE tblWledPattern (wledPattern_ID INTEGER PRIMARY KEY, scene_ID INT, server_ID INT, effect INT, pallette INT, color1 TEXT, color2 TEXT, color3 TEXT, speed INT, brightness INT, orderBy INT)",
    "CREATE TABLE tblLedTypeModel (ledTypeModel_ID INTEGER PRIMARY KEY, modelName TEXT, ledJSON TEXT)",
    "CREATE TABLE tblEffect (effect_ID INTEGER PRIMARY KEY, effectName TEXT, ef_ID INT)",
    "CREATE TABLE tblPallette (pallette_ID INTEGER PRIMARY KEY, palletteName TEXT, pa_ID INT)",
    "CREATE TABLE tblServersIP (ServerIP_ID INTEGER PRIMARY KEY, serverName TEXT, ipAddress TEXT)",
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

    def test_database_only_skips_uploads(self, env):
        """include_uploads=False: DB restores, images are NOT extracted (the
        Pi-Zero path — unzipping a big media tree crashes the box)."""
        x(env['live'], "INSERT INTO tblScenes(sceneName, active, orderBy) VALUES ('Keep Me', 1, 0)")
        snap = br.create_backup(label='manual')
        x(env['live'], "DELETE FROM tblScenes")
        os.remove(env['uploads'] / 'portraits' / 'hero.png')

        summary = br.restore_replace(snap, include_uploads=False)
        assert q(env['live'], "SELECT COUNT(*) FROM tblScenes WHERE sceneName='Keep Me'")[0][0] == 1
        assert summary['uploads_restored'] == 0
        assert not (env['uploads'] / 'portraits' / 'hero.png').exists()

        s = br.restore_merge(snap, include_uploads=False)
        assert s['uploads_added'] == 0
        assert not (env['uploads'] / 'portraits' / 'hero.png').exists()


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


class TestMergeSceneScoping:
    """Scene identity is (campaign, name) — the name-only matching used to
    funnel an archive's links into a same-named scene of a DIFFERENT campaign,
    scrambling it (the 'overwritten scene' bug)."""

    def _archive(self, env, build):
        src = str(env['tmp'] / 'scoped.db')
        make_db(src)
        build(src)
        old = sql.database
        sql.database = src
        try:
            return br.create_backup(label='scoped')
        finally:
            sql.database = old

    def test_same_name_in_other_campaign_is_a_new_scene(self, env):
        # local: 'Tavern' in campaign 'Home Game', with its own song + link
        x(env['live'], "INSERT INTO tblCampaigns(campaign_name, active, order_by) VALUES ('Home Game', 1, '1')")
        x(env['live'], "INSERT INTO tblScenes(sceneName, active, orderBy, campaign_id) VALUES ('Tavern', 1, 0, 1)")
        x(env['live'], "INSERT INTO tblMusic(path, song, urlSource, dnLoadStatus, videoId, displayName) "
                       "VALUES ('/tgt/', 'local0000001.mp3', 'https://l', 3, 'local0000001', 'Local Song')")
        x(env['live'], "INSERT INTO tblMusicScene(scene_ID, song_ID, orderBy, volume) VALUES (1, 1, 1, 70)")

        def build(src):
            x(src, "INSERT INTO tblCampaigns(campaign_name, active, order_by) VALUES ('Curse of Strahd', 1, '1')")
            x(src, "INSERT INTO tblScenes(sceneName, active, orderBy, campaign_id) VALUES ('Tavern', 1, 0, 1)")
            x(src, "INSERT INTO tblMusic(path, song, urlSource, dnLoadStatus, videoId, displayName) "
                   "VALUES ('/src/', 'strahd000001.mp3', 'https://s', 3, 'strahd000001', 'Strahd Song')")
            x(src, "INSERT INTO tblMusicScene(scene_ID, song_ID, orderBy, volume) VALUES (1, 1, 1, 80)")

        s = br.restore_merge(self._archive(env, build))
        assert s['scenes'] == 1                    # created, NOT matched cross-campaign
        scenes = q(env['live'],
                   "SELECT scene_ID, campaign_id FROM tblScenes WHERE sceneName='Tavern' ORDER BY scene_ID")
        assert len(scenes) == 2
        # the local scene's playlist is untouched — exactly its one local link
        local_links = q(env['live'], "SELECT song_ID FROM tblMusicScene WHERE scene_ID = 1")
        assert local_links == [(1,)]
        # the archive's link went to the NEW scene
        strahd_pk = q(env['live'], "SELECT song_id FROM tblMusic WHERE videoId='strahd000001'")[0][0]
        assert q(env['live'], "SELECT song_ID FROM tblMusicScene WHERE scene_ID = ?",
                 (scenes[1][0],)) == [(strahd_pk,)]

    def test_same_scene_same_campaign_appends_after_local_order(self, env):
        # local: campaign + scene already exist; playlist occupies orderBy 1..5
        x(env['live'], "INSERT INTO tblCampaigns(campaign_name, active, order_by) VALUES ('Shared', 1, '1')")
        x(env['live'], "INSERT INTO tblScenes(sceneName, active, orderBy, campaign_id) VALUES ('Castle Fight', 1, 0, 1)")
        x(env['live'], "INSERT INTO tblMusic(path, song, urlSource, dnLoadStatus, videoId, displayName) "
                       "VALUES ('/tgt/', 'local0000001.mp3', 'https://l', 3, 'local0000001', 'Local Song')")
        x(env['live'], "INSERT INTO tblMusicScene(scene_ID, song_ID, orderBy, volume) VALUES (1, 1, 5, 70)")

        def build(src):
            x(src, "INSERT INTO tblCampaigns(campaign_name, active, order_by) VALUES ('Shared', 1, '1')")
            x(src, "INSERT INTO tblScenes(sceneName, active, orderBy, campaign_id) VALUES ('Castle Fight', 1, 0, 1)")
            for i, vid in enumerate(('incoming00001', 'incoming00002'), start=1):
                x(src, "INSERT INTO tblMusic(path, song, urlSource, dnLoadStatus, videoId, displayName) "
                       f"VALUES ('/src/', '{vid}.mp3', 'https://u{i}', 3, '{vid}', 'Song {i}')")
                x(src, "INSERT INTO tblMusicScene(scene_ID, song_ID, orderBy, volume) VALUES (1, ?, ?, 80)",
                  (i, i))

        s = br.restore_merge(self._archive(env, build))
        assert s['scenes'] == 0                    # matched, not duplicated
        # incoming links appended AFTER the local ceiling (5), source order kept
        rows = q(env['live'],
                 "SELECT m.videoId, ms.orderBy FROM tblMusicScene ms "
                 "JOIN tblMusic m ON m.song_id = ms.song_ID "
                 "WHERE ms.scene_ID = 1 ORDER BY ms.orderBy")
        assert rows == [('local0000001', 5), ('incoming00001', 6), ('incoming00002', 7)]

    def test_duplicate_local_names_match_deterministically(self, env):
        x(env['live'], "INSERT INTO tblScenes(sceneName, active, orderBy) VALUES ('Tavern', 1, 0)")
        x(env['live'], "INSERT INTO tblScenes(sceneName, active, orderBy) VALUES ('tavern', 1, 1)")
        x(env['live'], "INSERT INTO tblMusic(path, song, urlSource, dnLoadStatus, videoId, displayName) "
                       "VALUES ('/tgt/', 'song00000001.mp3', 'https://l', 3, 'song00000001', 'Song')")

        def build(src):
            x(src, "INSERT INTO tblScenes(sceneName, active, orderBy) VALUES ('TAVERN', 1, 0)")
            x(src, "INSERT INTO tblMusic(path, song, urlSource, dnLoadStatus, videoId, displayName) "
                   "VALUES ('/src/', 'song00000001.mp3', 'https://l', 3, 'song00000001', 'Song')")
            x(src, "INSERT INTO tblMusicScene(scene_ID, song_ID, orderBy, volume) VALUES (1, 1, 1, 80)")

        s = br.restore_merge(self._archive(env, build))
        assert s['scenes'] == 0
        # lowest scene_ID wins, every time
        assert q(env['live'], "SELECT scene_ID FROM tblMusicScene") == [(1,)]


class TestOldArchiveCompat:
    def _old_archive(self, env):
        """Archive from a pre-videoId app version: media tables lack the
        videoId/displayName/metaStatus columns and tblMediaMetadata is absent."""
        src = str(env['tmp'] / 'ancient.db')
        conn = sqlite3.connect(src)
        for stmt in SCHEMA:
            if 'tblMediaMetadata' in stmt:
                continue
            if 'tblMusic (' in stmt or 'tblVideoMedia (' in stmt:
                stmt = stmt.split(', videoId')[0] + ')'
            conn.execute(stmt)
        conn.execute("INSERT INTO tblMusic(path, song, urlSource, dnLoadStatus) "
                     "VALUES ('/src/', 'legacy.mp3', 'https://u', 3)")
        conn.execute("INSERT INTO tblScenes(sceneName, active, orderBy) VALUES ('Old Scene', 1, 0)")
        conn.commit()
        conn.close()
        old = sql.database
        sql.database = src
        try:
            return br.create_backup(label='ancient')
        finally:
            sql.database = old

    def test_merge_from_pre_videoid_archive_completes(self, env):
        s = br.restore_merge(self._old_archive(env))
        assert s['scenes'] == 1                    # scenes still travel
        assert s['skipped_legacy'] == 1            # media has no dedup identity
        assert s['music'] == 0
        assert q(env['live'], "SELECT COUNT(*) FROM tblScenes WHERE sceneName='Old Scene'")[0][0] == 1

    def test_replace_upgrades_restored_schema(self, env):
        """restore_replace inside the app context (as the routes run it) must
        bring a restored old-version database up to the current schema."""
        import os as _os
        from flask import Flask
        from flask_migrate import Migrate
        from extensions import db
        archive = self._old_archive(env)
        app = Flask(__name__)
        app.config['SQLALCHEMY_DATABASE_URI'] = f"sqlite:///{env['live']}"
        app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        db.init_app(app)
        Migrate(app, db, directory=_os.path.join(
            _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), 'migrations'))
        with app.app_context():
            summary = br.restore_replace(archive)
        assert summary['schema_upgraded'] is True
        cols = [r[1] for r in q(env['live'], "PRAGMA table_info(tblMusic)")]
        assert 'videoId' in cols and 'metaStatus' in cols
        stamped = q(env['live'], "SELECT version_num FROM alembic_version")
        assert len(stamped) == 1 and stamped[0][0]   # stamped at the current head

    def test_replace_without_app_context_still_restores(self, env):
        archive = self._old_archive(env)
        summary = br.restore_replace(archive)
        assert summary['schema_upgraded'] is False   # upgrade deferred to next boot
        assert q(env['live'], "SELECT COUNT(*) FROM tblScenes WHERE sceneName='Old Scene'")[0][0] == 1


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


class TestMergePkeyCollisions:
    """The scenario that motivates the pk-remapping design: the archive's
    campaign/scene/media pkeys COLLIDE with local pkeys that hold entirely
    different content. The merge must never write source pkeys — local rows
    stay byte-identical, archive rows land under NEW pkeys, and every link
    follows the remap. (A naive pk-preserving import would overwrite
    'Waterdeep' with 'Curse of Strahd' here.)"""

    def _colliding_archive(self, env):
        src = str(env['tmp'] / 'colliding.db')
        make_db(src)
        # source pks all = 1, exactly like the local rows below
        x(src, "INSERT INTO tblCampaigns(campaign_id, campaign_name, active, order_by) "
               "VALUES (1, 'Curse of Strahd', 1, '1')")
        x(src, "INSERT INTO tblScenes(scene_ID, sceneName, active, orderBy, campaign_id) "
               "VALUES (1, 'Castle Fight', 1, 0, 1)")
        x(src, "INSERT INTO tblMusic(song_id, path, song, genre, urlSource, dnLoadStatus, "
               "videoId, displayName, metaStatus) "
               "VALUES (1, '/src/', 'strahdsong01.mp3', 0, 'https://s1', 3, "
               "'strahdsong01', 'Strahd Theme', 3)")
        x(src, "INSERT INTO tblMusicScene(scene_ID, song_ID, orderBy, volume) VALUES (1, 1, 1, 80)")
        old = sql.database
        sql.database = src
        try:
            return br.create_backup(label='collide')
        finally:
            sql.database = old

    def test_local_rows_untouched_archive_gets_new_pks(self, env):
        # LOCAL: different content occupying the SAME pkeys (all = 1)
        x(env['live'], "INSERT INTO tblCampaigns(campaign_id, campaign_name, active, order_by) "
                       "VALUES (1, 'Waterdeep', 1, '9')")
        x(env['live'], "INSERT INTO tblScenes(scene_ID, sceneName, active, orderBy, campaign_id) "
                       "VALUES (1, 'Harbor', 1, 5, 1)")
        x(env['live'], "INSERT INTO tblMusic(song_id, path, song, genre, urlSource, dnLoadStatus, "
                       "videoId, displayName, metaStatus) "
                       "VALUES (1, '/tgt/', 'harborsong01.mp3', 0, 'https://h1', 3, "
                       "'harborsong01', 'Harbor Song', 3)")
        x(env['live'], "INSERT INTO tblMusicScene(scene_ID, song_ID, orderBy, volume) VALUES (1, 1, 3, 55)")
        before_campaign = q(env['live'], "SELECT * FROM tblCampaigns WHERE campaign_id=1")
        before_scene    = q(env['live'], "SELECT * FROM tblScenes WHERE scene_ID=1")
        before_song     = q(env['live'], "SELECT * FROM tblMusic WHERE song_id=1")
        before_links    = q(env['live'], "SELECT * FROM tblMusicScene WHERE scene_ID=1")

        s = br.restore_merge(self._colliding_archive(env))
        assert (s['campaigns'], s['scenes'], s['music']) == (1, 1, 1)

        # local rows: byte-identical after the merge — nothing overwritten
        assert q(env['live'], "SELECT * FROM tblCampaigns WHERE campaign_id=1") == before_campaign
        assert q(env['live'], "SELECT * FROM tblScenes WHERE scene_ID=1") == before_scene
        assert q(env['live'], "SELECT * FROM tblMusic WHERE song_id=1") == before_song
        assert q(env['live'], "SELECT * FROM tblMusicScene WHERE scene_ID=1") == before_links

        # archive rows landed under NEW pkeys with the remap intact end-to-end
        new_camp = q(env['live'], "SELECT campaign_id FROM tblCampaigns "
                                  "WHERE campaign_name='Curse of Strahd'")[0][0]
        new_scene, scene_camp = q(env['live'], "SELECT scene_ID, campaign_id FROM tblScenes "
                                               "WHERE sceneName='Castle Fight'")[0]
        new_song = q(env['live'], "SELECT song_id FROM tblMusic WHERE videoId='strahdsong01'")[0][0]
        assert new_camp != 1 and new_scene != 1 and new_song != 1
        assert scene_camp == new_camp
        assert q(env['live'], "SELECT song_ID FROM tblMusicScene WHERE scene_ID=?",
                 (new_scene,)) == [(new_song,)]


class TestFullMerge:
    """restore_merge(full=True): the TTRPG tree + lighting, per the locked
    policy — users matched by username (else fallback), characters local-wins,
    sessions/maps merge by name, tokens/effects only for new maps, notes
    deduped, lighting only into scenes without local lighting."""

    def _boxes(self, env):
        live = env['live']
        # LOCAL box: dm + alice, alice already has 'Zdravko', a weapons-library
        # row under a DIFFERENT id than the source's, and an effect catalog
        # where 'Aurora' sits at a different index.
        x(live, "INSERT INTO tblUsers(username, display_name, role, active) VALUES ('dm', 'DM', 'dm', 1)")
        x(live, "INSERT INTO tblUsers(username, display_name, role, active) VALUES ('alice', 'Alice', 'player', 1)")
        x(live, "INSERT INTO tblCharacters(user_id, name, level, active, created_at) VALUES (2, 'Zdravko', 5, 1, 't')")
        x(live, "INSERT INTO tblWeaponsLibrary(weapon_lib_id, name, source) VALUES (40, 'Laser Sword', 'homebrew')")
        x(live, "INSERT INTO tblEffect(effect_ID, effectName, ef_ID) VALUES (9, 'Aurora', 9)")
        x(live, "INSERT INTO tblPallette(pallette_ID, palletteName, pa_ID) VALUES (7, 'Lava', 7)")

        # SOURCE box archive
        src = str(env['tmp'] / 'srcfull.db')
        make_db(src)
        x(src, "INSERT INTO tblUsers(username, display_name, role, active) VALUES ('alice', 'Alice', 'player', 1)")
        x(src, "INSERT INTO tblUsers(username, display_name, role, active) VALUES ('bob', 'Bob', 'player', 1)")
        # characters: Zdravko (alice — exists locally, must be skipped) and
        # Nova (bob — no local bob, lands under the fallback user)
        x(src, "INSERT INTO tblCharacters(user_id, name, level, active, created_at) VALUES (1, 'Zdravko', 9, 1, 't')")
        x(src, "INSERT INTO tblCharacters(user_id, name, level, active, created_at) VALUES (2, 'Nova', 3, 1, 't')")
        x(src, "INSERT INTO tblWeaponsLibrary(weapon_lib_id, name, source) VALUES (3, 'Laser Sword', 'homebrew')")
        x(src, "INSERT INTO tblCharacterWeapons(character_id, weapon_lib_id, weapon_name, damage_dice, equipped, order_by) "
               "VALUES (2, 3, 'Laser Sword', '1d8', 1, 1)")
        x(src, "INSERT INTO tblCharacterNotes(character_id, note_text, created_at) VALUES (2, 'backstory', 't')")
        x(src, "INSERT INTO tblCampaigns(campaign_name, active, order_by) VALUES ('Star Wars', 1, '1')")
        x(src, "INSERT INTO tblScenes(sceneName, active, orderBy, campaign_id) VALUES ('Bridge', 1, 0, 1)")
        x(src, "INSERT INTO tblSessions(title, session_number, campaign_id, status, dm_notes, created_at) "
               "VALUES ('Ep1', 1, 1, 'active', '', 't')")
        x(src, "INSERT INTO tblSessionParty(session_id, character_id, is_active, joined_at) VALUES (1, 1, 1, 't')")
        x(src, "INSERT INTO tblSessionParty(session_id, character_id, is_active, joined_at) VALUES (1, 2, 1, 't')")
        x(src, "INSERT INTO tblMonsterTemplates(name, cr, hp_max, ac, source, created_at) "
               "VALUES ('Gnark', '2', 30, 14, 'homebrew', 't')")
        x(src, "INSERT INTO tblSessionMonsters(session_id, template_id, display_name, hp_current, hp_max, ac, is_alive, sort_order) "
               "VALUES (1, 1, 'Gnark A', 30, 30, 14, 1, 0)")
        x(src, "INSERT INTO tblBattleMaps(session_id, name, grid_cols, grid_rows, is_active, sort_order, created_at) "
               "VALUES (1, 'Deck 5', 20, 20, 1, 0, 't')")
        x(src, "INSERT INTO tblBattleMapTokens(map_id, entity_type, entity_id, col, row, updated_at) "
               "VALUES (1, 'player', 1, 2, 3, 't')")   # Zdravko -> must remap to LOCAL char
        x(src, "INSERT INTO tblBattleMapTokens(map_id, entity_type, entity_id, col, row, updated_at) "
               "VALUES (1, 'monster', 1, 5, 5, 't')")  # Gnark A -> new session monster
        x(src, "INSERT INTO tblBattleMapEffects(map_id, shape, label, size_ft, created_at) "
               "VALUES (1, 'cloud', '', 20, 't')")
        x(src, "INSERT INTO tblSessionNotes(session_id, title, body, sort_order, created_at, updated_at) "
               "VALUES (1, 'Plot', 'the twist', 0, 't', 't')")
        x(src, "INSERT INTO tblBattleMapNotes(map_id, title, body, sort_order, created_at, updated_at) "
               "VALUES (1, 'Ambush', '3 goblins', 0, 't', 't')")
        # lighting: LED model + pattern, WLED server + pattern (Aurora at id 5
        # on the source, id 9 locally; Lava 3 -> 7)
        x(src, "INSERT INTO tblLedTypeModel(modelName, ledJSON) VALUES ('strip60', '{}')")
        x(src, "INSERT INTO tblScenePattern(scene_ID, ledTypeModel_ID, color, orderBy, outPin) "
               "VALUES (1, 1, '[1,2,3]', 0, 2)")
        x(src, "INSERT INTO tblEffect(effect_ID, effectName, ef_ID) VALUES (5, 'Aurora', 5)")
        x(src, "INSERT INTO tblPallette(pallette_ID, palletteName, pa_ID) VALUES (3, 'Lava', 3)")
        x(src, "INSERT INTO tblServersIP(serverName, ipAddress) VALUES ('wled1', '10.0.0.9')")
        x(src, "INSERT INTO tblWledPattern(scene_ID, server_ID, effect, pallette, color1, orderBy) "
               "VALUES (1, 1, 5, 3, '[9,9,9]', 0)")
        old = sql.database
        sql.database = src
        try:
            return br.create_backup(label='full')
        finally:
            sql.database = old

    def test_full_tree_merges(self, env):
        snap = self._boxes(env)
        s = br.restore_merge(snap, include_uploads=False, full=True, fallback_user_id=1)

        # characters: Nova imported under fallback (dm=1), Zdravko kept local
        assert s['characters'] == 1 and s['characters_skipped'] == 1
        assert q(env['live'], "SELECT user_id, level FROM tblCharacters WHERE name='Nova'") == [(1, 3)]
        assert q(env['live'], "SELECT level FROM tblCharacters WHERE name='Zdravko'") == [(5,)]  # untouched
        # Nova's weapon re-pointed at the LOCAL library id, note carried
        nova = q(env['live'], "SELECT character_id FROM tblCharacters WHERE name='Nova'")[0][0]
        assert q(env['live'], "SELECT weapon_lib_id FROM tblCharacterWeapons WHERE character_id=?", (nova,)) == [(40,)]
        assert q(env['live'], "SELECT note_text FROM tblCharacterNotes WHERE character_id=?", (nova,)) == [('backstory',)]

        # session imported, live-status downgraded
        assert s['sessions'] == 1
        assert q(env['live'], "SELECT status FROM tblSessions WHERE title='Ep1'") == [('planning',)]
        sid = q(env['live'], "SELECT session_id FROM tblSessions WHERE title='Ep1'")[0][0]
        # party: both members, Zdravko wired to the LOCAL character row
        zloc = q(env['live'], "SELECT character_id FROM tblCharacters WHERE name='Zdravko'")[0][0]
        party = {r[0] for r in q(env['live'], "SELECT character_id FROM tblSessionParty WHERE session_id=?", (sid,))}
        assert party == {zloc, nova} and s['party_links'] == 2

        # monsters + map + battle state
        assert s['session_monsters'] == 1 and s['maps'] == 1
        assert q(env['live'], "SELECT is_active FROM tblBattleMaps WHERE name='Deck 5'") == [(0,)]
        mid = q(env['live'], "SELECT map_id FROM tblBattleMaps WHERE name='Deck 5'")[0][0]
        gnark = q(env['live'], "SELECT monster_id FROM tblSessionMonsters WHERE display_name='Gnark A'")[0][0]
        toks = q(env['live'], "SELECT entity_type, entity_id FROM tblBattleMapTokens WHERE map_id=?", (mid,))
        assert ('player', zloc) in toks and ('monster', gnark) in toks and s['tokens'] == 2
        assert s['map_effects'] == 1

        # notes on both levels
        assert s['notes'] == 2
        assert q(env['live'], "SELECT body FROM tblSessionNotes WHERE session_id=?", (sid,)) == [('the twist',)]
        assert q(env['live'], "SELECT title FROM tblBattleMapNotes WHERE map_id=?", (mid,)) == [('Ambush',)]

        # lighting: LED model copied + remapped; WLED server copied, effect/
        # palette re-matched by name to the local catalog ids
        assert s['lighting'] == 2
        scene = q(env['live'], "SELECT scene_ID FROM tblScenes WHERE sceneName='Bridge'")[0][0]
        model = q(env['live'], "SELECT ledTypeModel_ID FROM tblLedTypeModel WHERE modelName='strip60'")[0][0]
        assert q(env['live'], "SELECT ledTypeModel_ID FROM tblScenePattern WHERE scene_ID=?", (scene,)) == [(model,)]
        srv = q(env['live'], "SELECT ServerIP_ID FROM tblServersIP WHERE serverName='wled1'")[0][0]
        assert q(env['live'], "SELECT server_ID, effect, pallette FROM tblWledPattern WHERE scene_ID=?", (scene,)) \
               == [(srv, 9, 7)]

    def test_full_merge_is_idempotent(self, env):
        snap = self._boxes(env)
        br.restore_merge(snap, include_uploads=False, full=True, fallback_user_id=1)
        s2 = br.restore_merge(snap, include_uploads=False, full=True, fallback_user_id=1)
        assert (s2['characters'], s2['sessions'], s2['maps'], s2['session_monsters'],
                s2['party_links'], s2['tokens'], s2['map_effects'], s2['notes'],
                s2['lighting']) == (0, 0, 0, 0, 0, 0, 0, 0, 0)

    def test_plain_merge_still_skips_ttrpg(self, env):
        snap = self._boxes(env)
        s = br.restore_merge(snap, include_uploads=False)   # full NOT set
        assert 'sessions' not in s
        assert q(env['live'], "SELECT COUNT(*) FROM tblSessions")[0][0] == 0
        assert q(env['live'], "SELECT COUNT(*) FROM tblCharacters")[0][0] == 1  # just local Zdravko


class TestLocalMediaLocate:
    """requeue_missing_media finds files already on this machine (row path,
    standard path, or anywhere under ~/Music|~/Videos by videoId filename)
    before queueing YouTube downloads."""

    def _home(self, env, monkeypatch):
        home = env['tmp'] / 'home'
        (home / 'Music' / 'SP').mkdir(parents=True)
        (home / 'Videos' / 'SP').mkdir(parents=True)
        monkeypatch.setattr(br, '_home', lambda: str(home))
        return home

    def test_found_in_alternate_folder_repoints_row(self, env, monkeypatch):
        home = self._home(env, monkeypatch)
        (home / 'Music' / 'OldLibrary').mkdir()
        (home / 'Music' / 'OldLibrary' / 'abc12345678.mp3').write_bytes(b'mp3')
        x(env['live'], "INSERT INTO tblMusic(path, song, urlSource, dnLoadStatus, videoId, displayName) "
                       "VALUES ('/gone/', 'abc12345678.mp3', 'https://u', 3, 'abc12345678', 'Song')")
        out = br.requeue_missing_media()
        assert out == {'requeued': 0, 'found_local': 1}
        path, status = q(env['live'], "SELECT path, dnLoadStatus FROM tblMusic")[0]
        assert path.endswith('OldLibrary' + os.sep) and status == 3

    def test_row_own_path_kept_when_valid(self, env, monkeypatch):
        home = self._home(env, monkeypatch)
        keep = home / 'elsewhere'
        keep.mkdir()
        (keep / 'abc12345678.mp3').write_bytes(b'mp3')
        x(env['live'], "INSERT INTO tblMusic(path, song, urlSource, dnLoadStatus, videoId, displayName) "
                       f"VALUES ('{keep}{os.sep}', 'abc12345678.mp3', 'https://u', 3, 'abc12345678', 'Song')")
        out = br.requeue_missing_media()
        assert out == {'requeued': 0, 'found_local': 0}       # nothing to fix
        assert q(env['live'], "SELECT path FROM tblMusic")[0][0] == f'{keep}{os.sep}'

    def test_queued_row_with_local_file_skips_download(self, env, monkeypatch):
        home = self._home(env, monkeypatch)
        (home / 'Music' / 'SP' / 'abc12345678.mp3').write_bytes(b'mp3')
        x(env['live'], "INSERT INTO tblMusic(path, song, urlSource, dnLoadStatus, videoId, displayName) "
                       "VALUES ('/wrong/', 'abc12345678.mp3', 'https://u', 1, 'abc12345678', 'Song')")
        out = br.requeue_missing_media()
        assert out == {'requeued': 0, 'found_local': 1}
        assert q(env['live'], "SELECT dnLoadStatus FROM tblMusic")[0][0] == 3

    def test_truly_absent_requeues_to_standard_path(self, env, monkeypatch):
        home = self._home(env, monkeypatch)
        x(env['live'], "INSERT INTO tblMusic(path, song, urlSource, dnLoadStatus, videoId, displayName) "
                       "VALUES ('/old/', 'abc12345678.mp3', 'https://u', 3, 'abc12345678', 'Song')")
        out = br.requeue_missing_media()
        assert out == {'requeued': 1, 'found_local': 0}
        path, status = q(env['live'], "SELECT path, dnLoadStatus FROM tblMusic")[0]
        assert path == str(home / 'Music' / 'SP') + os.sep and status == 1

    def test_merge_marks_already_local_files_downloaded(self, env, monkeypatch):
        home = self._home(env, monkeypatch)
        (home / 'Music' / 'SP' / 'newsong00001.mp3').write_bytes(b'mp3')
        src = str(env['tmp'] / 'srcloc.db')
        make_db(src)
        x(src, "INSERT INTO tblMusic(path, song, genre, urlSource, dnLoadStatus, videoId, displayName, metaStatus) "
               "VALUES ('/src/', 'newsong00001.mp3', 0, 'https://u2', 3, 'newsong00001', 'New Song', 3)")
        old = sql.database
        sql.database = src
        try:
            snap = br.create_backup(label='loc')
        finally:
            sql.database = old
        s = br.restore_merge(snap, include_uploads=False)
        assert s['music'] == 1 and s['found_local'] == 1
        assert q(env['live'], "SELECT dnLoadStatus FROM tblMusic WHERE videoId='newsong00001'")[0][0] == 3


class TestFullMergeOwnerFallback:
    def _archive_with_char(self, env, username='ghost'):
        src = str(env['tmp'] / 'srcowner.db')
        make_db(src)
        x(src, f"INSERT INTO tblUsers(username, display_name, role, active) VALUES ('{username}', 'G', 'player', 1)")
        x(src, "INSERT INTO tblCharacters(user_id, name, level, active, created_at) VALUES (1, 'Wisp', 2, 1, 't')")
        old = sql.database
        sql.database = src
        try:
            return br.create_backup(label='owner')
        finally:
            sql.database = old

    def test_unmatched_owner_resolves_to_dm_when_no_fallback_given(self, env):
        # Regression: user_map used to be built BEFORE the fallback was
        # resolved, baking None in as the owner -> NOT NULL abort.
        x(env['live'], "INSERT INTO tblUsers(username, display_name, role, active) VALUES ('dm', 'DM', 'dm', 1)")
        snap = self._archive_with_char(env)
        s = br.restore_merge(snap, include_uploads=False, full=True)  # no fallback param
        assert s['characters'] == 1 and s['characters_no_owner'] == 0
        assert q(env['live'], "SELECT user_id FROM tblCharacters WHERE name='Wisp'") == [(1,)]

    def test_no_users_at_all_reports_instead_of_silence(self, env):
        snap = self._archive_with_char(env)
        s = br.restore_merge(snap, include_uploads=False, full=True)
        assert s['characters'] == 0
        assert s['characters_no_owner'] == 1
        assert q(env['live'], "SELECT COUNT(*) FROM tblCharacters")[0][0] == 0

    def test_rerun_after_creating_users_heals_the_tree(self, env):
        """The exact recovery flow: first merge on a box with NO accounts
        (characters skipped), DM account created afterwards, merge re-run —
        characters, party links and player tokens must all land on the
        sessions/maps the FIRST merge already created."""
        src = str(env['tmp'] / 'srcheal.db')
        make_db(src)
        x(src, "INSERT INTO tblUsers(username, display_name, role, active) VALUES ('bob', 'B', 'player', 1)")
        x(src, "INSERT INTO tblCharacters(user_id, name, level, active, created_at) VALUES (1, 'Wisp', 2, 1, 't')")
        x(src, "INSERT INTO tblSessions(title, session_number, status, created_at) VALUES ('Ep9', 1, 'planning', 't')")
        x(src, "INSERT INTO tblSessionParty(session_id, character_id, is_active, joined_at) VALUES (1, 1, 1, 't')")
        x(src, "INSERT INTO tblBattleMaps(session_id, name, grid_cols, grid_rows, is_active, sort_order, created_at) "
               "VALUES (1, 'Cavern', 20, 20, 0, 0, 't')")
        x(src, "INSERT INTO tblBattleMapTokens(map_id, entity_type, entity_id, col, row, updated_at) "
               "VALUES (1, 'player', 1, 4, 4, 't')")
        old = sql.database
        sql.database = src
        try:
            snap = br.create_backup(label='heal')
        finally:
            sql.database = old

        # 1st merge: no accounts on this box — session+map merge, character can't
        s1 = br.restore_merge(snap, include_uploads=False, full=True)
        assert s1['sessions'] == 1 and s1['maps'] == 1
        assert s1['characters'] == 0 and s1['characters_no_owner'] == 1 and s1['tokens'] == 0

        # DM sets up the box, merge re-run
        x(env['live'], "INSERT INTO tblUsers(username, display_name, role, active) VALUES ('dm', 'DM', 'dm', 1)")
        s2 = br.restore_merge(snap, include_uploads=False, full=True)
        assert s2['sessions'] == 0 and s2['maps'] == 0          # no duplicates
        assert s2['characters'] == 1 and s2['party_links'] == 1
        assert s2['tokens'] == 1                                 # healed onto the EXISTING map
        wisp = q(env['live'], "SELECT character_id FROM tblCharacters WHERE name='Wisp'")[0][0]
        mid = q(env['live'], "SELECT map_id FROM tblBattleMaps WHERE name='Cavern'")[0][0]
        assert q(env['live'], "SELECT entity_id, col FROM tblBattleMapTokens WHERE map_id=?", (mid,)) == [(wisp, 4)]

        # 3rd run: fully idempotent now
        s3 = br.restore_merge(snap, include_uploads=False, full=True)
        assert (s3['characters'], s3['party_links'], s3['tokens']) == (0, 0, 0)


class TestCrossMachinePaths:
    """Paths from a different user or a different OS rebuild automatically:
    the foreign path simply fails the isfile probe and the row falls through
    to this machine's standard path / filename search / download queue."""

    def _home(self, env, monkeypatch):
        home = env['tmp'] / 'home'
        (home / 'Music' / 'SP').mkdir(parents=True)
        (home / 'Videos' / 'SP').mkdir(parents=True)
        monkeypatch.setattr(br, '_home', lambda: str(home))
        return home

    def test_windows_path_on_linux_with_file_present(self, env, monkeypatch):
        home = self._home(env, monkeypatch)
        (home / 'Music' / 'SP' / 'abc12345678.mp3').write_bytes(b'mp3')
        x(env['live'], "INSERT INTO tblMusic(path, song, urlSource, dnLoadStatus, videoId, displayName) "
                       r"VALUES ('C:\Users\bob/Music/SP/', 'abc12345678.mp3', 'https://u', 3, 'abc12345678', 'S')")
        out = br.requeue_missing_media()
        assert out == {'requeued': 0, 'found_local': 1}
        path, status = q(env['live'], "SELECT path, dnLoadStatus FROM tblMusic")[0]
        assert path == str(home) + '/Music/SP/' and status == 3

    def test_windows_path_on_linux_file_absent_requeues(self, env, monkeypatch):
        home = self._home(env, monkeypatch)
        x(env['live'], "INSERT INTO tblMusic(path, song, urlSource, dnLoadStatus, videoId, displayName) "
                       r"VALUES ('C:\Users\bob\Music\SP\\', 'abc12345678.mp3', 'https://u', 3, 'abc12345678', 'S')")
        out = br.requeue_missing_media()
        assert out == {'requeued': 1, 'found_local': 0}
        path, status = q(env['live'], "SELECT path, dnLoadStatus FROM tblMusic")[0]
        assert path == str(home) + '/Music/SP/' and status == 1

    def test_other_linux_user_path_found_via_index(self, env, monkeypatch):
        home = self._home(env, monkeypatch)
        (home / 'Videos' / 'Archive2019').mkdir()
        (home / 'Videos' / 'Archive2019' / 'vid000000001.mp4').write_bytes(b'mp4')
        x(env['live'], "INSERT INTO tblVideoMedia(path, title, urlSource, dnLoadStatus, videoId, displayName) "
                       "VALUES ('/home/otherguy/Videos/SP/', 'vid000000001.mp4', 'https://u', 3, 'vid000000001', 'V')")
        out = br.requeue_missing_media()
        assert out == {'requeued': 0, 'found_local': 1}
        path, status = q(env['live'], "SELECT path, dnLoadStatus FROM tblVideoMedia")[0]
        assert path.endswith('Archive2019' + os.sep) and status == 3

    def test_standard_paths_use_app_convention(self, env, monkeypatch):
        # requeued rows must get the same '<home>/Music/SP/' string the intake
        # code writes, so string comparisons across the app keep matching
        home = self._home(env, monkeypatch)
        x(env['live'], "INSERT INTO tblMusic(path, song, urlSource, dnLoadStatus, videoId, displayName) "
                       "VALUES ('/gone/', 'zzz.mp3', 'https://u', 3, 'zzz', 'S')")
        br.requeue_missing_media()
        assert q(env['live'], "SELECT path FROM tblMusic")[0][0] == f'{home}/Music/SP/'


class TestExtraSearchRoots:
    def _home(self, env, monkeypatch):
        home = env['tmp'] / 'home'
        (home / 'Music' / 'SP').mkdir(parents=True)
        (home / 'Videos' / 'SP').mkdir(parents=True)
        monkeypatch.setattr(br, '_home', lambda: str(home))
        return home

    def test_file_on_mounted_drive_found(self, env, monkeypatch):
        self._home(env, monkeypatch)
        drive = env['tmp'] / 'mnt' / 'media' / 'Music'
        drive.mkdir(parents=True)
        (drive / 'abc12345678.mp3').write_bytes(b'mp3')
        x(env['live'], "INSERT INTO tblAppSettings(name, value, typevalue) "
                       f"VALUES ('media_search_roots', '{drive}', 'text')")
        x(env['live'], "INSERT INTO tblMusic(path, song, urlSource, dnLoadStatus, videoId, displayName) "
                       "VALUES ('/home/otherguy/Music/SP/', 'abc12345678.mp3', 'https://u', 3, 'abc12345678', 'S')")
        out = br.requeue_missing_media()
        assert out == {'requeued': 0, 'found_local': 1}
        assert q(env['live'], "SELECT path FROM tblMusic")[0][0] == str(drive) + os.sep

    def test_multiple_roots_and_missing_root_tolerated(self, env, monkeypatch):
        self._home(env, monkeypatch)
        d2 = env['tmp'] / 'archive'
        d2.mkdir()
        (d2 / 'vid000000001.mp4').write_bytes(b'mp4')
        x(env['live'], "INSERT INTO tblAppSettings(name, value, typevalue) "
                       f"VALUES ('media_search_roots', '/does/not/exist;{d2}', 'text')")
        x(env['live'], "INSERT INTO tblVideoMedia(path, title, urlSource, dnLoadStatus, videoId, displayName) "
                       "VALUES ('/gone/', 'vid000000001.mp4', 'https://u', 3, 'vid000000001', 'V')")
        out = br.requeue_missing_media()
        assert out == {'requeued': 0, 'found_local': 1}
