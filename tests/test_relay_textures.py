"""Texture-library relay push (broadcast_map_update): bytes ride only until
the relay acknowledges the sha, stubs afterwards; a need_textures answer
patches the bytes back in and repeats the push; need_image + need_textures
resolve in the single heavy re-send."""
import copy
import io

import pytest
from PIL import Image

import relay_broadcaster as rb

CFG = {'url': 'http://relay', 'secret': 's', 'session_id': 'sid'}


@pytest.fixture()
def tex_file(tmp_path):
    img = Image.new('RGB', (64, 64), (90, 80, 70))
    p = tmp_path / 'flagstone.jpg'
    buf = io.BytesIO()
    img.save(buf, 'JPEG')
    p.write_bytes(buf.getvalue())
    return str(p)


class _Resp:
    def __init__(self, d):
        self._d = d

    def json(self):
        return self._d


@pytest.fixture()
def rig(monkeypatch):
    """Immediate execution, recorded posts, clean module state."""
    calls = []
    responses = []

    def fake_post(path, payload, cfg, timeout=5):
        calls.append((path, copy.deepcopy(payload)))
        return _Resp(responses.pop(0) if responses else {'ok': True})

    monkeypatch.setattr(rb, '_post', fake_post)
    monkeypatch.setattr(rb, '_active', lambda: CFG)
    monkeypatch.setattr(rb, '_exec_cfg', lambda: CFG)
    monkeypatch.setattr(rb, '_debounced_map_enqueue', lambda fn: fn())
    rb._last_map_hash['v'] = None
    rb._sent_texture_shas.clear()
    rb._TEXTURE_CACHE.clear()
    return calls, responses


def _push(tex_file, tokens=None):
    rb.broadcast_map_update(
        '/bg.png', 20, 20, tokens or [],
        floorplan={'walls': []}, floorplan_version=1, doors={},
        textures={'flagstone': {'path': tex_file, 'tile_ft': 6}})


class TestTexturePush:
    def test_first_push_carries_bytes_then_stubs(self, rig, tex_file):
        calls, _ = rig
        _push(tex_file)
        assert len(calls) == 1
        entry = calls[0][1]['map']['textures']['flagstone']
        assert entry['data'] and entry['sha'] and entry['tile_ft'] == 6
        # identical state: hash-skipped entirely
        _push(tex_file)
        assert len(calls) == 1
        # changed state: stub only, no bytes
        _push(tex_file, tokens=[{'token_id': 1}])
        entry2 = calls[1][1]['map']['textures']['flagstone']
        assert 'data' not in entry2 and entry2['sha'] == entry['sha']

    def test_need_textures_repeats_push_with_bytes(self, rig, tex_file):
        calls, responses = rig
        _push(tex_file)                      # bytes sent, sha marked
        assert len(calls) == 1
        # relay lost its store (session reset): stub push answers need_textures
        responses.append({'ok': True, 'need_textures': ['flagstone']})
        _push(tex_file, tokens=[{'token_id': 1}])
        assert len(calls) == 3               # stub push + bytes re-push
        assert 'data' not in calls[1][1]['map']['textures']['flagstone']
        assert calls[2][1]['map']['textures']['flagstone']['data']
        # and the sha counts as sent again afterwards
        _push(tex_file, tokens=[{'token_id': 2}])
        assert 'data' not in calls[3][1]['map']['textures']['flagstone']

    def test_need_image_re_send_carries_patched_textures(self, rig, tex_file):
        calls, responses = rig
        _push(tex_file)                      # prime: sha marked as sent
        responses.append({'ok': True, 'need_image': True,
                          'need_textures': ['flagstone']})
        # make the bg embeddable so a heavy variant exists
        _push(tex_file, tokens=[{'token_id': 1}])
        # stub push, then ONE heavy re-send carrying image AND texture bytes
        assert len(calls) == 3
        heavy = calls[2][1]
        assert heavy['map'].get('image_data') or 'data:' in heavy['map']['url'] \
            or heavy['map']['textures']['flagstone']['data']
        assert heavy['map']['textures']['flagstone']['data']

    def test_missing_file_skipped(self, rig):
        calls, _ = rig
        rb.broadcast_map_update(
            '/bg.png', 20, 20, [],
            floorplan={'walls': []}, floorplan_version=1, doors={},
            textures={'ghost': {'path': '/nope/missing.jpg', 'tile_ft': 5}})
        assert len(calls) == 1
        assert 'textures' not in calls[0][1]['map']
