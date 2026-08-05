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
    def test_both_ends_carry_the_room(self, settings):
        """MEASURED: a publisher inside a room is not reachable by stream id
        alone — ?view=<id> resolves nothing and the tile stays black. The view
        needs the room to find them, plus &scene so it renders ONE stream for
        OBS instead of a "Join Room" page."""
        settings['obs_vdo_room'] = 'dungeoncrawler'
        c = _char()
        assert '&room=dungeoncrawler' in c.video_push_url()
        view = c.video_view_url()
        assert '&room=dungeoncrawler' in view
        assert '&scene' in view

    def test_no_room_leaves_the_view_url_alone(self, settings):
        """Without a room the solo id works, and &scene would be noise."""
        view = _char().video_view_url()
        assert 'room=' not in view and 'scene' not in view

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
        # This OBS can capture the sink directly, so 'auto' means 'device'.
        # Declared as a CAPABILITY: the platform name is not what decides it.
        monkeypatch.setattr(obs_ws, 'audio_capture_kind',
                            lambda: 'pulse_output_capture')
        monkeypatch.setattr(ro, 'obs_is_local', lambda: True)
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


class TestAudioDeviceRebind:
    """Re-applying an identical device_id is a NO-OP in OBS — it keeps the
    handle it already holds. The music sink is destroyed and recreated every
    time the music player restarts, so that handle dies and the source reads
    silence forever while its settings still look perfect.

    Measured on a live rig with a tone playing: same-value write left the meter
    at 0.00000; nudging to another device and back gave 0.18362.
    """

    @pytest.fixture()
    def ws(self, monkeypatch):
        import obs_ws
        sent = []
        state = {'device_id': None}

        def fake_request(rtype, data=None, timeout=5):
            sent.append((rtype, (data or {}).get('inputSettings',
                                                 (data or {}))))
            if rtype == 'CreateInput':
                raise obs_ws.ObsRejected(601, 'already exists')
            if rtype == 'GetInputSettings':
                return {'inputSettings': {'device_id': state['device_id']}}
            if rtype == 'SetInputSettings':
                state['device_id'] = data['inputSettings'].get('device_id')
            if rtype == 'GetInputKindList':
                return {'inputKinds': ['pulse_output_capture']}
            return {}
        monkeypatch.setattr(obs_ws, 'request', fake_request)
        monkeypatch.setattr(obs_ws, 'audio_capture_kind',
                            lambda: 'pulse_output_capture')
        monkeypatch.setattr(obs_ws, 'scene_items', lambda n, **k: {'M': 1})
        return sent, state

    def _devices_written(self, sent):
        return [s.get('device_id') for t, s in sent
                if t == 'SetInputSettings']

    def test_same_device_is_nudged_to_force_a_reopen(self, ws):
        import obs_ws
        sent, state = ws
        state['device_id'] = 'sceneplay_music.monitor'
        obs_ws.ensure_audio_input('Party', 'M', 'sceneplay_music.monitor')
        written = self._devices_written(sent)
        assert written == ['default', 'sceneplay_music.monitor'], written

    def test_a_genuinely_new_device_needs_no_nudge(self, ws):
        """Changing the value re-opens on its own; nudging would be a needless
        extra dropout."""
        import obs_ws
        sent, state = ws
        state['device_id'] = 'something.else'
        obs_ws.ensure_audio_input('Party', 'M', 'sceneplay_music.monitor')
        assert self._devices_written(sent) == ['sceneplay_music.monitor']

    def test_the_wanted_device_is_always_what_lands(self, ws):
        import obs_ws
        sent, state = ws
        state['device_id'] = 'sceneplay_music.monitor'
        obs_ws.ensure_audio_input('Party', 'M', 'sceneplay_music.monitor')
        assert state['device_id'] == 'sceneplay_music.monitor'


class TestCaptureKindNeverGuessesNo:
    """An empty cache means "not primed yet", never "not supported".

    Answering None from an empty cache made music_transport() decide this OBS
    cannot capture local audio — which moves the music to a vdo.ninja feed
    that needs a browser tab nobody opened, and DELETES the working device
    capture on the way. A silent, destructive flip from a cache race.
    """

    def test_empty_cache_asks_obs_instead_of_answering_no(self, monkeypatch):
        import obs_ws
        asked = []

        def fake_request(rtype, data=None, timeout=3):
            asked.append(rtype)
            return {'inputKinds': ['browser_source', 'pulse_output_capture']}
        monkeypatch.setattr(obs_ws, 'request', fake_request)
        with obs_ws._cache_lock:
            obs_ws._cache['input_kinds'] = []
        assert obs_ws.audio_capture_kind() == 'pulse_output_capture'
        assert asked == ['GetInputKindList'], 'must have asked OBS'

    def test_the_live_answer_is_cached(self, monkeypatch):
        import obs_ws
        calls = []

        def fake_request(rtype, data=None, timeout=3):
            calls.append(rtype)
            return {'inputKinds': ['pulse_output_capture']}
        monkeypatch.setattr(obs_ws, 'request', fake_request)
        with obs_ws._cache_lock:
            obs_ws._cache['input_kinds'] = []
        obs_ws.audio_capture_kind()
        obs_ws.audio_capture_kind()
        assert len(calls) == 1, 'should not re-ask once it knows'

    def test_a_primed_cache_is_used_without_asking(self, monkeypatch):
        import obs_ws

        def boom(*a, **k):
            raise AssertionError('should not have asked OBS')
        monkeypatch.setattr(obs_ws, 'request', boom)
        with obs_ws._cache_lock:
            obs_ws._cache['input_kinds'] = ['pulse_output_capture']
        assert obs_ws.audio_capture_kind() == 'pulse_output_capture'

    def test_a_build_with_no_such_kind_still_answers_none(self, monkeypatch):
        """A genuine absence must still report None — that is what sends the
        music to a feed on a Mac or Windows OBS, correctly."""
        import obs_ws
        monkeypatch.setattr(obs_ws, 'request',
                            lambda *a, **k: {'inputKinds': ['browser_source']})
        with obs_ws._cache_lock:
            obs_ws._cache['input_kinds'] = []
        assert obs_ws.audio_capture_kind() is None

    def test_an_unreachable_obs_reports_none_without_raising(self, monkeypatch):
        import obs_ws

        def boom(*a, **k):
            raise obs_ws.ObsUnavailable('socket closed')
        monkeypatch.setattr(obs_ws, 'request', boom)
        with obs_ws._cache_lock:
            obs_ws._cache['input_kinds'] = []
        assert obs_ws.audio_capture_kind() is None
