"""Utilities → Downloads inventory (assets_inventory): media rows joined to
metadata with the title as the primary label, pictures with their owner,
totals, safe picture refs, and the streamed zip."""
import io
import sqlite3
import zipfile

import pytest

import assets_inventory as inv


@pytest.fixture
def env(tmp_path):
    db = str(tmp_path / 'a.db')
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE tblMusic (song_id INTEGER PRIMARY KEY, path TEXT, song TEXT, "
                 "displayName TEXT, dnLoadStatus INT)")
    conn.execute("CREATE TABLE tblVideoMedia (video_ID INTEGER PRIMARY KEY, path TEXT, title TEXT, "
                 "displayName TEXT, dnLoadStatus INT)")
    conn.execute("CREATE TABLE tblMediaMetadata (metadata_id INTEGER PRIMARY KEY, media_type TEXT, "
                 "media_id INT, title TEXT, duration INT, uploader TEXT, upload_date TEXT, active INT)")
    conn.execute("CREATE TABLE tblBattleMaps (map_id INTEGER PRIMARY KEY, name TEXT, bg_image TEXT)")
    mdir = tmp_path / 'Music'; mdir.mkdir()
    (mdir / 'abc.mp3').write_bytes(b'x' * 2048)
    conn.executemany("INSERT INTO tblMusic VALUES (?,?,?,?,?)", [
        (1, str(mdir) + '/', 'abc.mp3', 'My Typed Name', 3),
        (2, str(mdir) + '/', 'gone.mp3', '', 3),          # finished but file missing
        (3, str(mdir) + '/', 'queued.mp3', '', 1),        # not finished: excluded
    ])
    conn.execute("INSERT INTO tblMediaMetadata VALUES (1,'music',1,'Real Title',3725,'Chan','20240101',1)")
    up = tmp_path / 'uploads'; (up / 'battlemaps').mkdir(parents=True); (up / 'portraits').mkdir()
    (up / 'battlemaps' / 'cave.jpg').write_bytes(b'j' * 500)
    (up / 'portraits' / 'kara.png').write_bytes(b'p' * 100)
    (up / 'portraits' / '.hidden').write_bytes(b'h')
    conn.execute("INSERT INTO tblBattleMaps VALUES (1,'The Cave','cave.jpg')")
    conn.commit(); conn.close()
    return {'db': db, 'uploads': str(up), 'mdir': str(mdir)}


class TestMedia:
    def test_title_is_primary_and_size_from_disk(self, env):
        rows = inv.media_rows(env['db'], 'music')
        assert [r['id'] for r in rows] == [2, 1], 'finished only, newest first'
        r = {x['id']: x for x in rows}[1]
        assert r['name'] == 'Real Title' and r['display_name'] == 'My Typed Name'
        assert r['exists'] and r['size'] == 2048 and r['size_h'] == '2.0 KB'
        assert r['duration_h'] == '1:02:05' and r['uploader'] == 'Chan'

    def test_missing_file_flagged_and_falls_back_to_filename(self, env):
        r = {x['id']: x for x in inv.media_rows(env['db'], 'music')}[2]
        assert not r['exists'] and r['size'] is None and r['name'] == 'gone.mp3'

    def test_totals_count_only_present(self, env):
        t = inv.totals(inv.media_rows(env['db'], 'music'))
        assert t == {'count': 1, 'missing': 1, 'bytes': 2048, 'bytes_h': '2.0 KB'}

    def test_arc_name_uses_title_keeps_ext_scrubs(self, env):
        r = {x['id']: x for x in inv.media_rows(env['db'], 'music')}[1]
        r['name'] = 'D&D: "Fight" / Loop?'
        assert inv.arc_name(r, 'music') == 'music/D&D_ _Fight_ _ Loop_.mp3'


class TestPictures:
    def test_lists_folders_with_owner(self, env):
        rows = inv.picture_rows(env['db'], env['uploads'])
        assert [(r['folder'], r['file']) for r in rows] == [('battlemaps', 'cave.jpg'), ('portraits', 'kara.png')]
        assert rows[0]['used_by'] == 'The Cave' and rows[0]['size'] == 500
        assert rows[1]['used_by'] == '', 'no tblCharacters in this db — tolerated'

    def test_safe_ref(self):
        assert inv.safe_picture_ref('portraits', 'a.png')
        assert not inv.safe_picture_ref('portraits', '../a.png')
        assert not inv.safe_picture_ref('etc', 'passwd')
        assert not inv.safe_picture_ref('portraits', '.hidden')
        assert not inv.safe_picture_ref('portraits', '')


class TestZip:
    def test_streamed_zip_is_valid_and_dedupes_names(self, env, tmp_path):
        a = tmp_path / 'a.bin'; a.write_bytes(b'A' * 3000)
        b = tmp_path / 'b.bin'; b.write_bytes(b'B' * 10)
        chunks = list(inv.zip_stream([('music/x.mp3', str(a)), ('music/x.mp3', str(b)),
                                      ('music/nope.mp3', str(tmp_path / 'missing'))]))
        assert len(chunks) > 1, 'yielded incrementally'
        zf = zipfile.ZipFile(io.BytesIO(b''.join(chunks)))
        assert zf.testzip() is None
        assert sorted(zf.namelist()) == ['music/x (2).mp3', 'music/x.mp3']
        assert zf.read('music/x.mp3') == b'A' * 3000 and zf.read('music/x (2).mp3') == b'B' * 10
