"""The animated spotlight move.

Geometry lives in test_obs_layout; this covers the wire behaviour that makes
the reflow safe: every move ENDS exactly on its target (a tile stuck mid-slide
is a visible bug on stream), and a newer spotlight cancels an older one so
hammering the number keys can't leave two animations fighting.
"""
import threading
import time

import pytest

import obs_ws


@pytest.fixture
def sent(monkeypatch):
    """Capture frames instead of touching a socket."""
    frames = []
    lock = threading.Lock()

    def fake_send(frame):
        with lock:
            frames.append(frame)

    monkeypatch.setattr(obs_ws, '_send', fake_send)
    return frames


def _drain(predicate, timeout=3.0):
    """Wait for the animation thread rather than sleeping a fixed slice."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def _transforms(frames):
    out = []
    for f in frames:
        for req in (f.get('d') or {}).get('requests') or []:
            out.append(req['requestData']['sceneItemTransform'])
    return out


A = {'x': 0.0, 'y': 0.0, 'w': 100.0, 'h': 100.0}
B = {'x': 400.0, 'y': 200.0, 'w': 800.0, 'h': 600.0}


class TestAnimateItems:
    def test_lands_exactly_on_the_target(self, sent):
        obs_ws.animate_items('Party', [(7, A, B)], duration_s=0.05, steps=4)
        assert _drain(lambda: len(sent) >= 4)
        last = _transforms(sent)[-1]
        assert last['positionX'] == pytest.approx(B['x'])
        assert last['positionY'] == pytest.approx(B['y'])
        assert last['boundsWidth'] == pytest.approx(B['w'])
        assert last['boundsHeight'] == pytest.approx(B['h'])

    def test_moves_gradually_rather_than_snapping(self, sent):
        obs_ws.animate_items('Party', [(7, A, B)], duration_s=0.05, steps=6)
        assert _drain(lambda: len(sent) >= 6)
        widths = [t['boundsWidth'] for t in _transforms(sent)]
        assert widths == sorted(widths), 'the ease should never go backwards'
        assert widths[0] < B['w'], 'first frame should not already be there'
        assert len(set(widths)) > 2, 'that is a snap, not an animation'

    def test_every_tile_rides_in_one_batch_per_frame(self, sent):
        moves = [(1, A, B), (2, B, A), (3, A, B)]
        obs_ws.animate_items('Party', moves, duration_s=0.05, steps=3)
        assert _drain(lambda: len(sent) >= 3)
        for frame in sent:
            assert frame['op'] == 8, 'batched, not one request per tile'
            assert len(frame['d']['requests']) == 3

    def test_a_newer_move_supersedes_an_older_one(self, sent):
        obs_ws.animate_items('Party', [(7, A, B)], duration_s=3.0, steps=60)
        assert _drain(lambda: len(sent) >= 1)
        obs_ws.animate_items('Party', [(7, B, A)], duration_s=0.05, steps=4)
        assert _drain(lambda: any(
            t['boundsWidth'] == pytest.approx(A['w']) for t in _transforms(sent)))
        settled = len(sent)
        time.sleep(0.25)
        assert len(sent) - settled <= 1, 'the superseded animation kept running'

    def test_nothing_is_sent_for_a_no_op(self, sent):
        obs_ws.animate_items('Party', [], duration_s=0.05, steps=4)
        obs_ws.animate_items('Party', [(None, A, B)], duration_s=0.05, steps=4)
        obs_ws.animate_items('Party', [(7, A, B)], duration_s=0.0, steps=4)
        time.sleep(0.1)
        assert sent == []

    def test_a_dropped_link_stops_the_move_quietly(self, monkeypatch):
        def boom(frame):
            raise obs_ws.ObsUnavailable('socket closed')

        monkeypatch.setattr(obs_ws, '_send', boom)
        obs_ws.animate_items('Party', [(7, A, B)], duration_s=0.05, steps=4)
        time.sleep(0.1)     # the thread must die, not spin or raise


class TestUnfeatureLevelsTheGrid:
    """0 / G must ALWAYS level the party grid.

    It used to only switch to the configured wide shot, which did nothing to
    the layout — so with the wide shot set to the party scene itself (the
    obvious choice) the spotlight never went away."""

    @pytest.fixture
    def obs(self, monkeypatch):
        from routes import obs as obs_routes

        calls = {'synced': [], 'switched': []}
        monkeypatch.setattr(obs_routes, '_sync_party_scene',
                            lambda featured_id=None: calls['synced'].append(featured_id))
        monkeypatch.setattr(obs_routes, '_set_featured', lambda _cid: None)
        monkeypatch.setattr(obs_routes, '_cancel_return', lambda: None)
        monkeypatch.setattr(obs_ws, 'switch_scene',
                            lambda name, **kw: calls['switched'].append(name))
        return obs_routes, calls

    def test_levels_the_grid_when_no_wide_shot_is_configured(self, obs, monkeypatch):
        obs_routes, calls = obs
        monkeypatch.setattr(obs_routes, '_special_scene', lambda _k: '')
        obs_routes._unfeature()
        assert calls['synced'] == [None]
        assert calls['switched'] == []

    def test_levels_the_grid_even_with_a_wide_shot_configured(self, obs, monkeypatch):
        obs_routes, calls = obs
        monkeypatch.setattr(obs_routes, '_special_scene', lambda _k: 'Wide')
        monkeypatch.setattr(obs_ws, 'current_state', lambda: {'current_scene': 'Party'})
        obs_routes._unfeature()
        assert calls['synced'] == [None], 'the spotlight was left on the party scene'
        assert calls['switched'] == ['Wide']

    def test_does_not_re_cut_to_the_scene_it_is_already_on(self, obs, monkeypatch):
        obs_routes, calls = obs
        monkeypatch.setattr(obs_routes, '_special_scene', lambda _k: 'Party')
        monkeypatch.setattr(obs_ws, 'current_state', lambda: {'current_scene': 'Party'})
        obs_routes._unfeature()
        assert calls['synced'] == [None]
        assert calls['switched'] == [], 'a pointless cut flashes the transition'


class TestNoPointlessSourceWrites:
    """The blip. Writing a browser source's settings re-renders the page, so a
    live camera blanks for an instant; doing it to every tile on every
    spotlight change flashed the whole grid."""

    @pytest.fixture
    def calls(self, monkeypatch):
        from routes import obs as obs_routes

        seen = []

        def fake_ensure(scene, source, url, w, h, timeout=5, rewrite_settings=True):
            seen.append({'source': source, 'rewrite': rewrite_settings})
            return 1, []

        monkeypatch.setattr(obs_ws, 'ensure_browser_input', fake_ensure)
        obs_routes._input_settings.clear()
        yield obs_routes, seen
        obs_routes._input_settings.clear()

    def test_first_pass_writes_the_settings(self, calls):
        obs_routes, seen = calls
        obs_routes._ensure_input('S', 'Player - A', 'u', 640, 360, [])
        assert seen[-1]['rewrite'] is True

    def test_an_unchanged_repeat_writes_nothing(self, calls):
        obs_routes, seen = calls
        for _ in range(3):
            obs_routes._ensure_input('S', 'Player - A', 'u', 640, 360, [])
        assert [c['rewrite'] for c in seen] == [True, False, False]

    @pytest.mark.parametrize('after', [
        ('other', 640, 360), ('u', 1280, 360), ('u', 640, 720)])
    def test_a_real_change_still_writes(self, calls, after):
        obs_routes, seen = calls
        obs_routes._ensure_input('S', 'Player - A', 'u', 640, 360, [])
        obs_routes._ensure_input('S', 'Player - A', *after, [])
        assert [c['rewrite'] for c in seen] == [True, True]

    def test_a_failed_placement_is_not_remembered(self, calls, monkeypatch):
        """Otherwise a source that never got made would be skipped forever."""
        obs_routes, seen = calls
        monkeypatch.setattr(obs_ws, 'ensure_browser_input',
                            lambda *a, **k: (None, []))
        obs_routes._ensure_input('S', 'Player - A', 'u', 640, 360, [])
        monkeypatch.setattr(obs_ws, 'ensure_browser_input',
                            lambda *a, **k: seen.append({'rewrite': k['rewrite_settings']})
                            or (1, []))
        obs_routes._ensure_input('S', 'Player - A', 'u', 640, 360, [])
        assert seen[-1]['rewrite'] is True


class TestStableRenderSize:
    def test_every_tile_renders_at_the_spotlit_size(self):
        """So moving the spotlight is a transform, never a resize."""
        from obs_layout import grid_layout, spotlight_tile_size
        for n in range(2, 13):
            w, h = spotlight_tile_size(n, 1920, 1080)
            for featured in range(n):
                hero = grid_layout(n, 1920, 1080, featured=featured)[featured]
                assert (hero['w'], hero['h']) == (w, h), \
                    f'n={n}: the spotlit tile would need a different resolution'

    def test_it_is_the_largest_a_tile_ever_gets(self):
        from obs_layout import grid_layout, spotlight_tile_size
        for n in range(1, 13):
            w, h = spotlight_tile_size(n, 1920, 1080)
            every = grid_layout(n, 1920, 1080) + [
                t for f in range(n) for t in grid_layout(n, 1920, 1080, featured=f)]
            assert max(t['w'] for t in every) <= w + .01
            assert max(t['h'] for t in every) <= h + .01


class TestGlideSetting:
    """Broadcast > Party Scene > Spotlight glide (ms)."""

    @pytest.fixture
    def anim_ms(self, monkeypatch):
        from routes import obs as obs_routes

        stored = {}
        monkeypatch.setattr(obs_routes, 'appsettingGet',
                            lambda k, d='': stored.get(k, d))
        return obs_routes, stored

    def test_defaults_when_never_set(self, anim_ms):
        obs_routes, _ = anim_ms
        assert obs_routes._tile_anim_ms() == obs_routes.DEFAULT_TILE_ANIM_MS

    def test_reads_what_save_config_actually_stores(self, anim_ms):
        """save_config writes every clamped number as a float string, so a
        plain int() parse here would silently fall back to the default."""
        obs_routes, stored = anim_ms
        stored['obs_tile_anim_ms'] = '1200.0'
        assert obs_routes._tile_anim_ms() == 1200

    def test_zero_is_honoured_rather_than_read_as_unset(self, anim_ms):
        obs_routes, stored = anim_ms
        stored['obs_tile_anim_ms'] = '0.0'
        assert obs_routes._tile_anim_ms() == 0

    @pytest.mark.parametrize('raw,expected', [
        ('99999', 4000), ('-500', 0), ('', 700), ('nonsense', 700)])
    def test_clamps_and_survives_rubbish(self, anim_ms, raw, expected):
        obs_routes, stored = anim_ms
        stored['obs_tile_anim_ms'] = raw
        assert obs_routes._tile_anim_ms() == expected


class TestEase:
    def test_starts_and_ends_where_it_should(self):
        assert obs_ws._ease(0.0) == pytest.approx(0.0)
        assert obs_ws._ease(1.0) == pytest.approx(1.0)

    def test_is_monotonic(self):
        vals = [obs_ws._ease(i / 40) for i in range(41)]
        assert vals == sorted(vals)

    def test_eases_in_and_out(self):
        """Slow at the ends, quick through the middle — that is the look."""
        assert obs_ws._ease(0.1) < 0.1
        assert obs_ws._ease(0.9) > 0.9
        assert obs_ws._ease(0.5) == pytest.approx(0.5)
