"""Reusing uploads by reference (shared_assets): ref shapes, resolution,
validation against the disk/whitelist, and the "is anyone else using this
file" guard that stops an owner's replace from deleting a shared file."""
import os
import sqlite3

import pytest

import shared_assets as sa


@pytest.fixture
def env(tmp_path):
    root = tmp_path
    for f in ('portraits', 'battlemaps', 'monsters', 'obs'):
        (root / 'static' / 'uploads' / f).mkdir(parents=True)
    (root / 'static/uploads/battlemaps/cave.jpg').write_bytes(b'x')
    (root / 'static/uploads/portraits/kara.png').write_bytes(b'x')
    vdir = root / 'Videos'; vdir.mkdir(); (vdir / 'clip.mp4').write_bytes(b'v')
    db = str(root / 'a.db'); c = sqlite3.connect(db)
    c.execute("CREATE TABLE tblVideoMedia (video_ID INTEGER PRIMARY KEY, path TEXT, title TEXT, dnLoadStatus INT)")
    c.execute("INSERT INTO tblVideoMedia VALUES (5, ?, 'clip.mp4', 3)", (str(vdir) + '/',))
    c.execute("INSERT INTO tblVideoMedia VALUES (6, ?, 'pending.mp4', 1)", (str(vdir) + '/',))
    c.execute("CREATE TABLE tblCharacters (character_id INTEGER PRIMARY KEY, portrait_path TEXT)")
    c.execute("CREATE TABLE tblBattleMaps (map_id INTEGER PRIMARY KEY, bg_image TEXT)")
    c.execute("CREATE TABLE tblMonsterTemplates (template_id INTEGER PRIMARY KEY, stats_json TEXT)")
    c.execute("CREATE TABLE tblAppSettings (name TEXT, value TEXT)")
    c.commit(); c.close()
    return str(root), db


class TestRefs:
    def test_shapes(self):
        assert sa.picture_ref('portraits', 'battlemaps', 'cave.jpg') == '../battlemaps/cave.jpg'
        assert sa.picture_ref('portraits', 'portraits', 'kara.png') == 'kara.png'
        assert sa.video_ref(5, 'mp4') == '../../../assets/media/video/5.mp4'
        assert sa.is_ref('../x/y.png') and not sa.is_ref('y.png') and not sa.is_ref('')

    def test_resolve(self, env):
        root, db = env
        assert sa.resolve_path(root, db, 'portraits', 'kara.png') == os.path.join(root, 'static/uploads/portraits/kara.png')
        assert sa.resolve_path(root, db, 'portraits', '../battlemaps/cave.jpg') == os.path.join(root, 'static/uploads/battlemaps/cave.jpg')
        assert sa.resolve_path(root, db, 'obs', '../../../assets/media/video/5.mp4').endswith('Videos/clip.mp4')
        assert sa.resolve_path(root, db, 'obs', '../../../assets/media/video/5.webm') is None, 'ext must match'
        assert sa.resolve_path(root, db, 'obs', '../../../assets/media/video/6.mp4') is None, 'unfinished download'
        assert sa.resolve_path(root, db, 'portraits', '../etc/passwd') is None
        assert sa.resolve_path(root, db, 'portraits', '../../app.py') is None
        assert sa.resolve_path(root, db, 'portraits', 'sub/dir.png') is None

    def test_valid_ref(self, env):
        root, db = env
        assert sa.valid_ref(root, db, 'portraits', '../battlemaps/cave.jpg', kinds=('image',))
        assert not sa.valid_ref(root, db, 'portraits', '../battlemaps/missing.jpg')
        assert not sa.valid_ref(root, db, 'portraits', 'kara.png'), 'bare names are not refs'
        assert sa.valid_ref(root, db, 'battlemaps', '../../../assets/media/video/5.mp4')
        assert not sa.valid_ref(root, db, 'obs', '../../../assets/media/video/5.mp4', kinds=('image',))


class TestReferencedElsewhere:
    def test_by_ref_and_by_url_and_same_folder(self, env):
        root, db = env
        c = sqlite3.connect(db)
        c.execute("INSERT INTO tblCharacters VALUES (1, '../battlemaps/cave.jpg')")
        c.execute("INSERT INTO tblBattleMaps VALUES (7, 'cave.jpg')")
        c.execute("INSERT INTO tblBattleMaps VALUES (8, 'cave.jpg')")
        c.execute("INSERT INTO tblMonsterTemplates VALUES (3, '{\"image\": \"/static/uploads/portraits/kara.png\"}')")
        c.execute("INSERT INTO tblAppSettings VALUES ('obs_title_image', '../portraits/kara.png')")
        c.commit(); c.close()
        # map 7 owns cave.jpg; a character refs it AND map 8 shares the name
        assert sa.referenced_elsewhere(db, 'battlemaps', 'cave.jpg', exclude=('tblBattleMaps', 'map_id', 7))
        # kara.png: monster stats + OBS setting point at it
        assert sa.referenced_elsewhere(db, 'portraits', 'kara.png')
        assert not sa.referenced_elsewhere(db, 'portraits', 'nobody.png')

    def test_owner_alone_is_not_elsewhere(self, env):
        root, db = env
        c = sqlite3.connect(db)
        c.execute("INSERT INTO tblBattleMaps VALUES (7, 'cave.jpg')"); c.commit(); c.close()
        assert not sa.referenced_elsewhere(db, 'battlemaps', 'cave.jpg', exclude=('tblBattleMaps', 'map_id', 7))
        assert sa.referenced_elsewhere(db, 'battlemaps', 'cave.jpg'), 'no exclusion: the owner counts'
