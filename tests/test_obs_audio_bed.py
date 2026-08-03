"""Table audio: the vdo.ninja room, and keeping sound alive across a cut.

OBS renders a source's audio only while that source is in the CURRENT scene
(global mic/desktop devices excepted). The camera sources live in the party
scene, so cutting to the battle map silenced every player mid-sentence. The
fix is a nested 'ScenePlay Audio' scene parked off-canvas — heard, never seen.
"""
import pytest

from models.ttrpg import tblCharacters


@pytest.fixture()
def settings(app, monkeypatch):
    store = {}
    import routes.obs as ro
    import sql
    fake = lambda name, default=None: store.get(name, default)   # noqa: E731
    monkeypatch.setattr(sql, 'appsettingGet', fake)
    monkeypatch.setattr(ro, 'appsettingGet', fake)
    return store


def _char(**over):
    base = dict(character_id=7, user_id=1, name='Kara', level=1,
                hp_current=5, hp_max=5, created_at='2026-01-01 00:00:00',
                video_stream_id='abc123')
    base.update(over)
    return tblCharacters(**base)


class TestRoom:
    def test_room_joins_the_push_link_only(self, settings):
        """Players join the room; OBS keeps watching each stream solo so every
        camera keeps its own fader instead of arriving pre-mixed."""
        settings['obs_vdo_room'] = 'dungeoncrawler'
        c = _char()
        assert '&room=dungeoncrawler' in c.video_push_url()
        assert 'room=' not in c.video_view_url()

    def test_no_room_configured_changes_nothing(self, settings):
        c = _char()
        assert c.video_push_url() == \
            'https://vdo.ninja/?push=abc123&webcam&autostart'

    def test_room_name_is_url_encoded(self, settings):
        """A room with a space would otherwise truncate the link."""
        settings['obs_vdo_room'] = 'my table&x'
        assert '&room=my%20table%26x' in _char().video_push_url()

    def test_room_already_in_push_params_is_not_doubled(self, settings):
        """A DM who typed the room into the raw params keeps exactly one."""
        settings['obs_vdo_room'] = 'here'
        settings['obs_vdo_push_params'] = '&webcam&room=there'
        url = _char().video_push_url()
        assert url.count('room=') == 1
        assert 'room=there' in url

    def test_room_and_password_ride_together(self, settings):
        settings['obs_vdo_room'] = 'table'
        settings['obs_vdo_password'] = 'sesame'
        url = _char().video_push_url()
        assert '&room=table' in url and '&password=sesame' in url


class TestMusicDevice:
    def test_defaults_to_the_music_players_own_sink(self, app, settings):
        """Not the desktop: the sink carries the music alone, so it cannot
        pick the players back up out of OBS monitoring and loop."""
        import routes.obs as ro
        assert ro.music_device_id() == 'sceneplay_music.monitor'

    def test_device_is_overridable(self, app, settings):
        import routes.obs as ro
        settings['obs_music_device'] = 'something.else.monitor'
        assert ro.music_device_id() == 'something.else.monitor'

    def test_capture_defaults_on(self, app, settings):
        import routes.obs as ro
        assert ro.music_capture_on() is True
        settings['obs_music_capture'] = '0'
        assert ro.music_capture_on() is False


class TestAudioBed:
    """_build_audio against a recording stub of obs_ws.

    The party scene is the single source of truth: it is nested into every
    other scene, so whoever can be heard there can be heard everywhere.
    """

    @pytest.fixture()
    def obs(self, monkeypatch, settings):
        import obs_ws
        import routes.obs as ro
        calls = {'audio': [], 'nested': [], 'placed': [], 'removed': [],
                 'requests': []}
        scenes = ['ScenePlay Party', 'ScenePlay Map', 'ScenePlay Pre',
                  'ScenePlay Intermission', 'ScenePlay Post']
        monkeypatch.setattr(obs_ws, 'scene_list',
                            lambda refresh=False: (list(scenes), scenes[0]))
        monkeypatch.setattr(
            obs_ws, 'ensure_audio_input',
            lambda sc, n, dev, **k: calls['audio'].append((sc, n, dev)) or 1)
        monkeypatch.setattr(
            obs_ws, 'ensure_nested_scene',
            lambda p, c, **k: calls['nested'].append((p, c)) or 9)
        monkeypatch.setattr(
            obs_ws, 'place_item',
            lambda sc, i, rect, **k: calls['placed'].append((sc, rect)))
        monkeypatch.setattr(obs_ws, 'set_item_enabled',
                            lambda sc, i, on, **k: None)
        monkeypatch.setattr(
            obs_ws, 'remove_item',
            lambda sc, i, **k: calls['removed'].append((sc, i)))
        monkeypatch.setattr(obs_ws, 'scene_items', lambda n, **k: {})
        monkeypatch.setattr(
            obs_ws, 'request',
            lambda t, d=None, **k: calls['requests'].append((t, d)) or {})
        monkeypatch.setattr(ro, '_ordered_party', lambda *a, **k: [_char()])
        return calls

    def test_party_is_nested_into_every_other_scene(self, app, settings, obs):
        import routes.obs as ro
        ro._build_audio(1920, 1080, [])
        assert set(obs['nested']) == {
            ('ScenePlay Map', 'ScenePlay Party'),
            ('ScenePlay Pre', 'ScenePlay Party'),
            ('ScenePlay Intermission', 'ScenePlay Party'),
            ('ScenePlay Post', 'ScenePlay Party')}

    def test_party_is_never_nested_into_itself(self, app, settings, obs):
        """A scene containing itself recurses forever."""
        import routes.obs as ro
        ro._build_audio(1920, 1080, [])
        assert 'ScenePlay Party' not in [p for p, _c in obs['nested']]

    def test_nested_party_is_parked_off_canvas(self, app, settings, obs):
        """Heard, never seen — otherwise the whole party layout lands on top
        of the battle map."""
        import routes.obs as ro
        ro._build_audio(1920, 1080, [])
        assert obs['placed'], 'the nested item was never positioned'
        for _sc, rect in obs['placed']:
            assert rect['x'] >= 1920, 'would be drawn over the scene'

    def test_music_goes_into_the_party_scene_only(self, app, settings, obs):
        """Every other scene inherits it by nesting; adding it to each one as
        well would be the same capture active twice."""
        import routes.obs as ro
        ro._build_audio(1920, 1080, [])
        assert obs['audio'] == [('ScenePlay Party', ro.MUSIC_SOURCE_NAME,
                                 'sceneplay_music.monitor')]

    def test_music_capture_can_be_switched_off(self, app, settings, obs):
        import routes.obs as ro
        settings['obs_music_capture'] = '0'
        ro._build_audio(1920, 1080, [])
        assert obs['audio'] == []

    def test_missing_music_device_warns_and_keeps_building(
            self, app, settings, obs, monkeypatch):
        """The sink only exists while the music player is running; that must
        not stop the voices being wired up."""
        import obs_ws
        import routes.obs as ro

        def boom(*a, **k):
            raise obs_ws.ObsRejected(600, 'no such device')
        monkeypatch.setattr(obs_ws, 'ensure_audio_input', boom)
        warnings = []
        ro._build_audio(1920, 1080, warnings)
        assert warnings and 'music' in warnings[0].lower()
        assert obs['nested'], 'the voices were abandoned too'


class TestLegacyCleanup:
    """The previous arrangement must be taken back out, or its sources stay
    active alongside the nested party scene — the same audio twice."""

    @pytest.fixture()
    def obs(self, monkeypatch, settings):
        import obs_ws
        import routes.obs as ro
        scenes = ['ScenePlay Party', 'ScenePlay Map', 'ScenePlay Audio']
        contents = {
            'ScenePlay Party': {'ScenePlay Music': 11},
            'ScenePlay Map': {'ScenePlay Audio': 22, 'ScenePlay Music': 33},
            'ScenePlay Audio': {'Player - Kara Cam': 44},
        }
        calls = {'removed': [], 'requests': []}
        monkeypatch.setattr(obs_ws, 'scene_list',
                            lambda refresh=False: (list(scenes), scenes[0]))
        monkeypatch.setattr(obs_ws, 'scene_items',
                            lambda n, **k: dict(contents.get(n, {})))
        monkeypatch.setattr(
            obs_ws, 'remove_item',
            lambda sc, i, **k: calls['removed'].append((sc, i)))
        monkeypatch.setattr(
            obs_ws, 'request',
            lambda t, d=None, **k: calls['requests'].append((t, d)) or {})
        monkeypatch.setattr(ro, '_ordered_party', lambda *a, **k: [_char()])
        return calls

    def test_old_audio_scene_is_unnested_and_deleted(self, app, settings, obs):
        import routes.obs as ro
        ro._drop_legacy_audio_scene([])
        assert ('ScenePlay Map', 22) in obs['removed']
        assert ('RemoveScene', {'sceneName': 'ScenePlay Audio'}) \
            in obs['requests']

    def test_music_is_stripped_from_every_scene_but_party(
            self, app, settings, obs):
        import routes.obs as ro
        ro._drop_legacy_audio_scene([])
        assert ('ScenePlay Map', 33) in obs['removed']
        assert ('ScenePlay Party', 11) not in obs['removed'], \
            'the party scene is where the music belongs now'
