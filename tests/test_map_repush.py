"""Map auto-repush: the receiver re-sends the live battle map when the relay's
stored map_json stays stale/missing (dropped push, relay restart) so late
joiners get the current map without the DM touching anything.

Pure tests: the out-of-sync decision, and the streak/cooldown gating with the
actual push stubbed out.
"""

import json
import time
import types

import pytest

import relay_receiver as rr


IDS = {1, 2, 3}


def _map(tokens=None, url='/battlemaps/aaa.png'):
    return json.dumps({'url': url,
                       'tokens': [{'token_id': t} for t in (tokens or [])]})


class TestMapOutOfSync:
    def test_missing_or_unparseable(self):
        assert rr._map_out_of_sync(None, IDS, None) is True
        assert rr._map_out_of_sync('', IDS, None) is True
        assert rr._map_out_of_sync('not json{', IDS, None) is True

    def test_alien_token_ids(self):
        assert rr._map_out_of_sync(_map([1, 99]), IDS, None) is True

    def test_subset_ids_in_sync(self):
        # subset, not equality: pushes legitimately omit dead entities
        assert rr._map_out_of_sync(_map([1, 2]), IDS, None) is False

    def test_bg_mismatch(self):
        assert rr._map_out_of_sync(_map([1], url='/battlemaps/old.png'),
                                   IDS, 'new.png') is True
        assert rr._map_out_of_sync(_map([1], url='/battlemaps/new.png'),
                                   IDS, 'new.png') is False

    def test_bg_missing_on_relay(self):
        assert rr._map_out_of_sync(_map([1], url=''), IDS, 'new.png') is True

    def test_non_relay_bg_urls_trusted(self):
        # co-located http URL / data: URL can't be compared — trust them
        assert rr._map_out_of_sync(_map([1], url='http://lan/x.png'),
                                   IDS, 'new.png') is False
        assert rr._map_out_of_sync(_map([1], url='data:image/png;base64,x'),
                                   IDS, 'new.png') is False

    def test_no_bg_expected_skips_bg_check(self):
        assert rr._map_out_of_sync(_map([1], url=''), IDS, None) is False


@pytest.fixture
def repush_env(monkeypatch):
    """Reset gating state, stub the push, freeze/control time."""
    rr._map_resync.update(streak=0, last=0.0, cooldown=rr._MAP_RESYNC_COOLDOWN)
    pushes = []
    monkeypatch.setattr(rr, '_do_repush', lambda bm: pushes.append(bm))
    clock = {'t': 1000.0}
    monkeypatch.setattr(time, 'monotonic', lambda: clock['t'])
    bm = types.SimpleNamespace(map_id=7, tokens=[], bg_image='')
    return pushes, clock, bm


class TestMaybeRepushGating:
    def test_needs_persistent_mismatch(self, repush_env):
        pushes, clock, bm = repush_env
        for _ in range(rr._MAP_RESYNC_POLLS - 1):
            rr._maybe_repush_map(bm, None)
        assert pushes == []                       # not persistent enough yet
        rr._maybe_repush_map(bm, None)
        assert pushes == [bm]                     # third consecutive miss fires

    def test_in_sync_resets_streak_and_cooldown(self, repush_env):
        pushes, clock, bm = repush_env
        rr._maybe_repush_map(bm, None)
        rr._maybe_repush_map(bm, None)
        rr._map_resync['cooldown'] = 500.0
        rr._maybe_repush_map(bm, _map([]))        # relay in sync again
        assert rr._map_resync['streak'] == 0
        assert rr._map_resync['cooldown'] == rr._MAP_RESYNC_COOLDOWN
        for _ in range(rr._MAP_RESYNC_POLLS - 1):
            rr._maybe_repush_map(bm, None)
        assert pushes == []                       # streak really restarted

    def test_cooldown_blocks_and_doubles(self, repush_env):
        pushes, clock, bm = repush_env
        for _ in range(rr._MAP_RESYNC_POLLS):
            rr._maybe_repush_map(bm, None)
        assert len(pushes) == 1
        # mismatch persists: within cooldown nothing more is sent
        for _ in range(10):
            rr._maybe_repush_map(bm, None)
        assert len(pushes) == 1
        assert rr._map_resync['cooldown'] == rr._MAP_RESYNC_COOLDOWN * 2
        # after the (already-doubled) cooldown expires it fires again
        clock['t'] += rr._MAP_RESYNC_COOLDOWN * 2 + 1
        rr._maybe_repush_map(bm, None)
        assert len(pushes) == 2
        assert rr._map_resync['cooldown'] == rr._MAP_RESYNC_COOLDOWN * 4

    def test_cooldown_caps_at_15_minutes(self, repush_env):
        pushes, clock, bm = repush_env
        rr._map_resync['cooldown'] = 900.0
        for _ in range(rr._MAP_RESYNC_POLLS):
            rr._maybe_repush_map(bm, None)
        clock['t'] += 901
        rr._maybe_repush_map(bm, None)
        assert rr._map_resync['cooldown'] == 900.0
