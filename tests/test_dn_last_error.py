"""Per-row download-error diagnostics.

extract_ytdlp_error distills a yt-dlp log into the ERROR lines (WARNING lines
as fallback — e.g. the missing-JS-runtime deprecation that causes bogus
'not available' failures). update_dn_last_error stores/clears the text on the
media row so a failure survives the next run overwriting ytdlp_last.log.
"""

import sqlite3

import pytest

import sql
from sql import update_dn_last_error
from yt_que import extract_ytdlp_error


SAMPLE_LOG = """\
/x/.venv/bin/python -m yt_dlp -f best --output=abc.mp4 https://youtube.com/watch?v=abc

[youtube] Extracting URL: https://www.youtube.com/watch?v=abc
[youtube] abc: Downloading webpage
WARNING: [youtube] No supported JavaScript runtime could be found. Only deno is enabled by default
[youtube] abc: Downloading android vr player API JSON
ERROR: [youtube] abc: This video is not available
"""


class TestExtractYtdlpError:
    def test_error_lines_win(self):
        assert extract_ytdlp_error(SAMPLE_LOG) == \
            'ERROR: [youtube] abc: This video is not available'

    def test_warnings_surface_when_no_error(self):
        log = SAMPLE_LOG.replace('ERROR: [youtube] abc: This video is not available\n', '')
        out = extract_ytdlp_error(log)
        assert out.startswith('WARNING: [youtube] No supported JavaScript runtime')

    def test_multiple_errors_joined(self):
        log = 'ERROR: one\nnoise\nERROR: two\n'
        assert extract_ytdlp_error(log) == 'ERROR: one | ERROR: two'

    def test_empty_and_clean_logs(self):
        assert extract_ytdlp_error('') == ''
        assert extract_ytdlp_error(None) == ''
        assert extract_ytdlp_error('[youtube] abc: Downloading webpage\n') == ''

    def test_capped_length(self):
        log = '\n'.join(f'ERROR: {i} ' + 'x' * 200 for i in range(50))
        assert len(extract_ytdlp_error(log)) <= 1000


@pytest.fixture
def mdb(tmp_path, monkeypatch):
    db = str(tmp_path / 'media.db')
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE tblMusic (song_id INTEGER PRIMARY KEY, dnLastError TEXT)")
    conn.execute("CREATE TABLE tblVideoMedia (video_ID INTEGER PRIMARY KEY, dnLastError TEXT)")
    conn.execute("INSERT INTO tblMusic(song_id) VALUES (1)")
    conn.execute("INSERT INTO tblVideoMedia(video_ID) VALUES (1)")
    conn.commit()
    conn.close()
    monkeypatch.setattr(sql, 'database', db)
    return db


def _err(db, table, pkcol):
    conn = sqlite3.connect(db)
    val = conn.execute(f"SELECT dnLastError FROM {table} WHERE {pkcol} = 1").fetchone()[0]
    conn.close()
    return val


class TestUpdateDnLastError:
    def test_store_and_clear_music(self, mdb):
        update_dn_last_error('tblMusic', 1, 'ERROR: boom')
        assert _err(mdb, 'tblMusic', 'song_id') == 'ERROR: boom'
        update_dn_last_error('tblMusic', 1, '')
        assert _err(mdb, 'tblMusic', 'song_id') == ''

    def test_store_video(self, mdb):
        update_dn_last_error('tblVideoMedia', 1, 'ERROR: nope')
        assert _err(mdb, 'tblVideoMedia', 'video_ID') == 'ERROR: nope'
        assert _err(mdb, 'tblMusic', 'song_id') is None   # untouched
