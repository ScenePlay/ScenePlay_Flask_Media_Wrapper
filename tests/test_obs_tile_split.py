"""A camera tile is TWO OBS sources: the bare feed, and the name strip above it.

It used to be one source whose page framed the feed. That is unfixable over
plain http: an https iframe inside an http parent is not a secure context, so
WebRTC never starts and vdo.ninja renders nothing. Measured inside OBS itself —
the same view URL shows the camera as a top-level source and is black one
iframe deep, while a framed example.com renders fine. &cleanoutput then hides
the error, so the only symptom is a silent black rectangle.

These lock in the split, because the failure it fixes is invisible: every
source is present, enabled and correctly sized while showing nothing.
"""
import os

import pytest
from flask import Flask

from extensions import db
from models.ttrpg import tblCharacters

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture()
def page_app(monkeypatch):
    """The shared `app` fixture registers no blueprints, and the thing under
    test here is what the tile TEMPLATE renders — so mount the real blueprint
    against the real template folder."""
    from routes.obs import obs_bp
    a = Flask(__name__,
              template_folder=os.path.join(REPO, 'templates'),
              static_folder=os.path.join(REPO, 'static'))
    a.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    a.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    a.config['SECRET_KEY'] = 'test'
    db.init_app(a)
    a.register_blueprint(obs_bp)
    with a.app_context():
        db.create_all()
        yield a
        db.session.rollback()
        db.drop_all()


@pytest.fixture()
def settings(app, monkeypatch):
    """Same reason as test_obs_feed: routes.obs holds its own binding."""
    store = {}
    import routes.obs as ro
    import sql
    fake = lambda name, default=None: store.get(name, default)   # noqa: E731
    monkeypatch.setattr(sql, 'appsettingGet', fake)
    monkeypatch.setattr(ro, 'appsettingGet', fake)
    return store


def _char(**over):
    base = dict(character_id=7, user_id=1, name='Kara', level=1,
                hp_current=5, hp_max=5, created_at='2026-01-01 00:00:00')
    base.update(over)
    return tblCharacters(**base)


class TestTilePlan:
    def test_camera_tile_is_feed_plus_strip(self, app, settings):
        """The player's own source is the BARE feed — never the tile page."""
        import routes.obs as ro
        c = _char(video_stream_id='abc123')
        with app.test_request_context():
            url, strip = ro._tile_plan(c, presence={}, overrides=set())
        assert url == c.video_view_url()
        assert url.startswith('https://vdo.ninja/')
        # The thing that was broken: the source must not be our page framing
        # the feed.
        assert '/tile/' not in url
        assert strip is not None and strip.endswith('&strip=1')

    def test_pinned_player_keeps_the_feed_as_their_source(self, app, settings):
        """THE audio rule: pinning someone to their card must not tear down
        their WebRTC connection, or it cuts their microphone mid-sentence.
        The card is drawn OVER the still-running camera instead."""
        import routes.obs as ro
        c = _char(video_stream_id='abc123')
        with app.test_request_context():
            url, overlay = ro._tile_plan(c, presence={}, overrides={7})
        assert url == c.video_view_url(), 'the feed must keep running'
        assert '/card/' in overlay
        assert 'over=1' in overlay, 'a see-through card would show the camera'

    def test_stale_feed_also_keeps_the_source(self, app, settings, monkeypatch):
        """Same for a player the relay stopped hearing from: their picture is
        replaced, their audio is not."""
        import routes.obs as ro
        monkeypatch.setattr(ro, '_feed_state', lambda *a, **k: 'stale')
        c = _char(video_stream_id='abc123')
        with app.test_request_context():
            url, overlay = ro._tile_plan(c, presence={}, overrides=set())
        assert url == c.video_view_url()
        assert 'over=1' in overlay

    def test_no_feed_configured_falls_back_to_card(self, app, settings):
        """Nothing to keep alive, so the card IS the source and needs no
        overlay above it."""
        import routes.obs as ro
        c = _char(video_stream_id='')
        with app.test_request_context():
            url, overlay = ro._tile_plan(c, presence={}, overrides=set())
        assert '/card/' in url
        assert 'over=1' not in url, 'nothing behind it to hide'
        assert overlay is None

    def test_overlay_source_is_managed(self, app, settings):
        """Pruning and the reload-all sweep only touch prefixed sources; an
        overlay that misses the prefix would be orphaned in the scene."""
        import routes.obs as ro
        c = _char(video_stream_id='abc123')
        with app.test_request_context():
            name = ro._overlay_source_name_for(c)
        assert name.startswith(ro._MANAGED_PREFIXES)
        assert name != ro._source_name_for(c)


class TestTileAudio:
    """Where each camera source's sound goes in the OBS mixer."""

    @pytest.fixture()
    def obs(self, monkeypatch):
        """Record what would be asked of OBS."""
        import obs_ws
        calls = {'mute': [], 'monitor': []}
        monkeypatch.setattr(obs_ws, 'set_input_mute',
                            lambda n, m, **k: calls['mute'].append((n, m)))
        monkeypatch.setattr(obs_ws, 'set_audio_monitor',
                            lambda n, t, **k: calls['monitor'].append((n, t)))
        return calls

    def test_dm_tile_is_muted_by_default(self, app, settings, obs):
        """The DM's tile is their own mic returning to them — unmuted it
        doubles their voice on the broadcast and can howl when monitored."""
        import routes.obs as ro
        dm = _char(character_id=ro.DM_TILE_ID, name='DM')
        ro._apply_tile_audio('DM - DM Cam', dm, [])
        assert obs['mute'] == [('DM - DM Cam', True)]

    def test_dm_tile_can_be_unmuted(self, app, settings, obs):
        import routes.obs as ro
        settings['obs_dm_audio'] = '1'
        dm = _char(character_id=ro.DM_TILE_ID, name='DM')
        ro._apply_tile_audio('DM - DM Cam', dm, [])
        assert obs['mute'] == [('DM - DM Cam', False)]

    def test_players_are_never_muted(self, app, settings, obs):
        import routes.obs as ro
        ro._apply_tile_audio('Player - Kara Cam', _char(), [])
        assert obs['mute'] == [('Player - Kara Cam', False)]

    def test_monitoring_is_off_by_default(self, app, settings, obs):
        """Off still reaches the stream — it only decides whether the DM hears
        it locally, and most tables are already on a voice call."""
        import obs_ws
        import routes.obs as ro
        ro._apply_tile_audio('Player - Kara Cam', _char(), [])
        assert obs['monitor'] == [('Player - Kara Cam', obs_ws.MONITOR_OFF)]

    def test_monitoring_can_be_turned_on(self, app, settings, obs):
        import obs_ws
        import routes.obs as ro
        settings['obs_feed_monitor'] = '1'
        ro._apply_tile_audio('Player - Kara Cam', _char(), [])
        assert obs['monitor'] == [('Player - Kara Cam', obs_ws.MONITOR_ROOM)]

    def test_missing_monitor_device_does_not_fail_the_build(
            self, app, settings, obs, monkeypatch):
        """OBS with no monitoring device rejects the call. The feed still
        reaches the stream, so a scene build must not die over it."""
        import obs_ws
        import routes.obs as ro

        def boom(*a, **k):
            raise obs_ws.ObsRejected(600, 'no monitoring device')
        monkeypatch.setattr(obs_ws, 'set_audio_monitor', boom)
        warnings = []
        ro._apply_tile_audio('Player - Kara Cam', _char(), warnings)
        assert warnings == []


class TestStripPage:
    def _get(self, page_app, settings, strip):
        import routes.obs as ro
        settings['obs_dm_stream_id'] = 'abc123'
        settings['obs_dm_enabled'] = '1'
        with page_app.app_context():
            tok = ro._card_token(ro.DM_TILE_ID)
        q = f'?t={tok}' + ('&strip=1' if strip else '')
        r = page_app.test_client().get('/ttrpg/obs/tile/dm' + q)
        assert r.status_code == 200, r.status_code
        return r.data

    def test_strip_mode_drops_the_iframe(self, page_app, settings):
        body = self._get(page_app, settings, strip=True)
        assert b'<iframe' not in body, 'framing the feed is what was black'
        assert b'background: transparent' in body, \
            'an opaque strip would hide the camera source underneath'
        # It is still the character strip, not an empty page.
        assert b'id="strip"' in body

    def test_default_mode_still_frames_the_feed(self, page_app, settings):
        """Unchanged for an https parent — the relay serves this page too."""
        body = self._get(page_app, settings, strip=False)
        assert b'<iframe' in body
        assert b'background: transparent' not in body


class TestCardPage:
    def _get(self, page_app, settings, over):
        import routes.obs as ro
        settings['obs_dm_enabled'] = '1'
        with page_app.app_context():
            tok = ro._card_token(ro.DM_TILE_ID)
        q = f'?t={tok}' + ('&over=1' if over else '')
        r = page_app.test_client().get('/ttrpg/obs/card/dm' + q)
        assert r.status_code == 200, r.status_code
        return r.data

    def test_overlay_card_is_opaque(self, page_app, settings):
        """A see-through card would let the camera it is hiding show around
        the panel's edges."""
        body = self._get(page_app, settings, over=True)
        assert b'background: transparent' not in body
        assert b'#14151b' in body

    def test_overlay_card_does_not_claim_there_is_no_camera(
            self, page_app, settings):
        """It is covering a camera that is still running and still audible."""
        assert b'no camera' not in self._get(page_app, settings, over=True)

    def test_standalone_card_stays_transparent(self, page_app, settings):
        """As the source itself it composites over the scene background."""
        body = self._get(page_app, settings, over=False)
        assert b'background: transparent' in body
        assert b'no camera' in body
