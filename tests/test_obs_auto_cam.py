"""The auto-camera watch (routes.obs): a feed that renders black swaps that
player to their stat card; light coming back swaps them to camera.

Unit level: OBS and the screenshot probe are stubbed — what's pinned down is
the vote hysteresis (2 dark passes to swap away, 1 lit pass back), the tile
decision honouring the dark set, and the off-switch clearing all state."""
import pytest

from models.ttrpg import tblCharacters


@pytest.fixture()
def ro(monkeypatch):
    import routes.obs as ro
    ro._auto_dark_ids.clear()
    ro._cam_dark_votes.clear()
    yield ro
    ro._auto_dark_ids.clear()
    ro._cam_dark_votes.clear()


@pytest.fixture()
def settings(app, monkeypatch):
    store = {'obs_auto_cam': '1'}
    import routes.obs as ro
    import sql
    fake = lambda name, default=None: store.get(name, default)   # noqa: E731
    monkeypatch.setattr(sql, 'appsettingGet', fake)
    monkeypatch.setattr(ro, 'appsettingGet', fake)
    return store


def _char(cid=7):
    return tblCharacters(character_id=cid, user_id=1, name='Kara', level=1,
                         hp_current=1, hp_max=1,
                         created_at='2026-01-01 00:00:00',
                         video_stream_id='abc')


@pytest.fixture()
def rig(ro, settings, monkeypatch):
    import obs_ws
    kara = _char()
    monkeypatch.setattr(obs_ws, 'connected', lambda: True)
    monkeypatch.setattr(ro, '_ordered_party', lambda *a, **k: [kara])
    probe = {'dark': False}
    monkeypatch.setattr(ro, '_probe_camera_dark', lambda src: probe['dark'])
    return kara, probe


class TestScanVotes:
    def test_one_dark_pass_does_not_swap(self, app, rig, ro):
        _kara, probe = rig
        probe['dark'] = True
        ro._scan_cameras()
        assert 7 not in ro._auto_dark_ids, 'one pass could be a reconnect blip'

    def test_two_dark_passes_swap_to_card(self, app, rig, ro):
        _kara, probe = rig
        probe['dark'] = True
        ro._scan_cameras()
        ro._scan_cameras()
        assert 7 in ro._auto_dark_ids

    def test_one_lit_pass_swaps_back(self, app, rig, ro):
        _kara, probe = rig
        probe['dark'] = True
        ro._scan_cameras()
        ro._scan_cameras()
        probe['dark'] = False
        ro._scan_cameras()
        assert 7 not in ro._auto_dark_ids, 'a returning face shows fast'
        assert ro._cam_dark_votes[7] == 0

    def test_a_failed_probe_keeps_the_current_state(self, app, rig, ro,
                                                    monkeypatch):
        _kara, probe = rig
        probe['dark'] = True
        ro._scan_cameras()
        ro._scan_cameras()
        def boom(src):
            raise RuntimeError('scene not built')
        monkeypatch.setattr(ro, '_probe_camera_dark', boom)
        ro._scan_cameras()
        assert 7 in ro._auto_dark_ids, 'no vote, no change'

    def test_turning_off_clears_everything(self, app, rig, ro, settings):
        _kara, probe = rig
        probe['dark'] = True
        ro._scan_cameras()
        ro._scan_cameras()
        settings['obs_auto_cam'] = '0'
        ro._scan_cameras()
        assert not ro._auto_dark_ids and not ro._cam_dark_votes


class TestTileDecision:
    def test_dark_feed_shows_the_card(self, app, rig, ro, monkeypatch):
        kara, _probe = rig
        monkeypatch.setattr(ro, '_presence', lambda: {})
        ro._auto_dark_ids.add(7)
        assert '/card/7' in ro._tile_url(kara, {}, set())
        feed, overlay = ro._tile_plan(kara, {}, set())
        assert feed == kara.video_view_url(), 'feed source stays — mic survives'
        assert 'over=1' in overlay, 'card overlays the (dark) camera'

    def test_lit_feed_shows_the_camera(self, app, rig, ro, monkeypatch):
        kara, _probe = rig
        monkeypatch.setattr(ro, '_presence', lambda: {})
        assert '/tile/7' in ro._tile_url(kara, {}, set())


class TestWatchPacing:
    """The watch paces itself: fast while a feed is dark or in doubt, idle
    when every camera is lit, a bare setting read when the feature is off."""

    def test_off_is_slowest(self, app, rig, ro, settings):
        settings['obs_auto_cam'] = '0'
        assert ro._cam_watch_seconds() == ro.AUTO_CAM_OFF_S

    def test_all_lit_idles(self, app, rig, ro):
        ro._scan_cameras()
        assert ro._cam_watch_seconds() == ro.AUTO_CAM_IDLE_S

    def test_pending_vote_goes_fast(self, app, rig, ro):
        _kara, probe = rig
        probe['dark'] = True
        ro._scan_cameras()                     # one vote, not yet swapped
        assert ro._cam_watch_seconds() == ro.AUTO_CAM_FAST_S

    def test_swapped_to_card_stays_fast(self, app, rig, ro):
        _kara, probe = rig
        probe['dark'] = True
        ro._scan_cameras()
        ro._scan_cameras()
        assert 7 in ro._auto_dark_ids
        assert ro._cam_watch_seconds() == ro.AUTO_CAM_FAST_S, \
            'a returning face must be spotted quickly'

    def test_fast_is_far_quicker_than_the_feed_watch(self, ro):
        assert ro.AUTO_CAM_FAST_S * ro.AUTO_CAM_DARK_PASSES < ro.DEFAULT_WATCH_S / 2
