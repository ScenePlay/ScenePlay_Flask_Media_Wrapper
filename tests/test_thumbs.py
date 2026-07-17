"""ThumbnailStore: download → Pillow-shrink → atomic save, plus the worker's
one-per-poll backfill sweep. Network is stubbed — a fake requests.get serves
Pillow-generated images."""
import os
import sqlite3
from io import BytesIO

import pytest
from PIL import Image

import thumbs
from thumbs import ThumbnailStore


def png_bytes(width, height, color=(200, 30, 30)):
    buf = BytesIO()
    Image.new('RGB', (width, height), color).save(buf, 'PNG')
    return buf.getvalue()


class FakeResponse:
    def __init__(self, content, status=200):
        self.content = content
        self.status = status

    def raise_for_status(self):
        if self.status != 200:
            raise RuntimeError(f'HTTP {self.status}')


@pytest.fixture()
def store(tmp_path, monkeypatch):
    st = ThumbnailStore(directory=str(tmp_path / 'thumbs'), max_width=320)
    st._responses = {}
    monkeypatch.setattr(thumbs.requests, 'get',
                        lambda url, timeout=0: st._responses[url])
    return st


class TestStore:
    def test_downscales_wide_image(self, store):
        store._responses['https://x/big.png'] = FakeResponse(png_bytes(1280, 720))
        assert store.cache('music', 7, 'https://x/big.png') is True
        img = Image.open(store.path('music', 7))
        assert img.format == 'JPEG'
        assert img.size == (320, 180)          # aspect preserved
        assert os.path.getsize(store.path('music', 7)) < 20_000

    def test_small_image_not_upscaled(self, store):
        store._responses['https://x/small.png'] = FakeResponse(png_bytes(120, 90))
        store.cache('video', 3, 'https://x/small.png')
        assert Image.open(store.path('video', 3)).size == (120, 90)

    def test_url_only_when_cached(self, store):
        assert store.url('music', 7) is None
        store._responses['https://x/a.png'] = FakeResponse(png_bytes(100, 100))
        store.cache('music', 7, 'https://x/a.png')
        assert store.url('music', 7) == '/static/thumbs/music_7.jpg'

    def test_failures_return_false_never_raise(self, store):
        assert store.cache('music', 1, None) is False
        assert store.cache('music', 1, '') is False
        store._responses['https://x/404.png'] = FakeResponse(b'', status=404)
        assert store.cache('music', 1, 'https://x/404.png') is False
        store._responses['https://x/junk.png'] = FakeResponse(b'not an image')
        assert store.cache('music', 1, 'https://x/junk.png') is False
        assert not store.exists('music', 1)    # no partial file left behind


class TestBackfill:
    @pytest.fixture()
    def env(self, tmp_path, monkeypatch, store):
        import sql
        import meta_que
        db = str(tmp_path / 'live.db')
        conn = sqlite3.connect(db)
        conn.execute("CREATE TABLE tblMediaMetadata (metadata_id INTEGER PRIMARY KEY, "
                     "media_type TEXT, media_id INT, thumbnail TEXT)")
        conn.execute("INSERT INTO tblMediaMetadata(media_type, media_id, thumbnail) "
                     "VALUES ('music', 1, 'https://x/1.png')")
        conn.execute("INSERT INTO tblMediaMetadata(media_type, media_id, thumbnail) "
                     "VALUES ('music', 2, 'https://x/2.png')")
        conn.execute("INSERT INTO tblMediaMetadata(media_type, media_id, thumbnail) "
                     "VALUES ('video', 3, '')")   # no URL -> ignored
        conn.commit()
        conn.close()
        monkeypatch.setattr(sql, 'database', db)
        monkeypatch.setattr(meta_que, 'thumb_store', store)
        monkeypatch.setattr(meta_que, '_thumb_next_scan', 0.0)
        monkeypatch.setattr(meta_que, '_thumb_failed', set())
        store._responses['https://x/1.png'] = FakeResponse(png_bytes(640, 480))
        store._responses['https://x/2.png'] = FakeResponse(png_bytes(640, 480))
        return store

    def test_one_per_call_until_clean(self, env):
        from meta_que import backfill_one_thumbnail
        assert backfill_one_thumbnail() is True    # music/1
        assert env.exists('music', 1) and not env.exists('music', 2)
        assert backfill_one_thumbnail() is True    # music/2
        assert env.exists('music', 2)
        assert backfill_one_thumbnail() is False   # clean -> sweep goes dormant
        assert backfill_one_thumbnail() is False   # ...and stays dormant (rescan timer)

    def test_failed_url_not_retried(self, env):
        import meta_que
        env._responses['https://x/1.png'] = FakeResponse(b'', status=500)
        assert meta_que.backfill_one_thumbnail() is True    # attempted music/1, failed
        assert not env.exists('music', 1)
        assert meta_que.backfill_one_thumbnail() is True    # moves ON to music/2
        assert env.exists('music', 2)
        assert ('music', 1) in meta_que._thumb_failed
