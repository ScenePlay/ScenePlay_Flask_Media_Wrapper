"""Audio has to be wired AFTER every scene exists.

_build_audio nests the party scene into the map and show scenes. Run it before
those are created — which is what happens on a first build, or the first after
the DM wipes their OBS collection — and it nests into nothing at all. The build
reports success, the party scene sounds fine, and the table goes silent the
moment the program cuts anywhere else.
"""
import pytest


@pytest.fixture()
def settings(app, monkeypatch):
    store = {}
    import routes.obs as ro
    import sql
    fake = lambda name, default=None: store.get(name, default)   # noqa: E731
    monkeypatch.setattr(sql, 'appsettingGet', fake)
    monkeypatch.setattr(ro, 'appsettingGet', fake)
    return store


class TestBuildOrder:
    def test_sync_party_scene_does_not_wire_audio(self, app, settings,
                                                  monkeypatch):
        """It runs before the other scenes exist, and featuring a player comes
        through here too — neither is a moment to re-wire audio."""
        import routes.obs as ro
        import inspect
        src = inspect.getsource(ro._sync_party_scene)
        assert '_build_audio(' not in src, \
            'audio wired too early — the show scenes do not exist yet'

    def test_build_party_wires_audio_after_the_show_scenes(self, app, settings):
        """Order matters: ensure_show_scenes() must come first."""
        import routes.obs as ro
        import inspect
        src = inspect.getsource(ro.api_build_party)
        assert '_build_audio(' in src, 'the build never wires audio at all'
        assert src.index('ensure_show_scenes()') < src.index('_build_audio('), \
            'audio is wired before the scenes it nests into exist'
        assert src.index('ensure_map_scene()') < src.index('_build_audio(')


class TestBuildAudioNeedsScenes:
    def test_nothing_happens_when_no_scenes_exist(self, app, settings,
                                                  monkeypatch):
        """The early return is what made this silent rather than loud."""
        import obs_ws
        import routes.obs as ro
        calls = []
        monkeypatch.setattr(obs_ws, 'scene_list',
                            lambda refresh=False: ([], ''))
        monkeypatch.setattr(
            obs_ws, 'ensure_audio_input',
            lambda *a, **k: calls.append('audio'))
        monkeypatch.setattr(
            obs_ws, 'ensure_nested_scene', lambda *a, **k: calls.append('nest'))
        ro._build_audio(1920, 1080, [])
        assert calls == []

    def test_party_alone_still_gets_its_music(self, app, settings, monkeypatch):
        """Even with no other scenes yet, the music belongs in the party scene
        — the nesting is what has to wait."""
        import obs_ws
        import routes.obs as ro
        calls = {'audio': [], 'nested': []}
        monkeypatch.setattr(obs_ws, 'scene_list',
                            lambda refresh=False: (['ScenePlay Party'], ''))
        monkeypatch.setattr(obs_ws, 'scene_items', lambda n, **k: {})
        monkeypatch.setattr(obs_ws, 'remove_item', lambda *a, **k: None)
        monkeypatch.setattr(obs_ws, 'request', lambda *a, **k: {})
        monkeypatch.setattr(obs_ws, 'audio_capture_kind',
                            lambda: 'pulse_output_capture')
        monkeypatch.setattr(ro, 'obs_is_local', lambda: True)
        monkeypatch.setattr(
            obs_ws, 'ensure_audio_input',
            lambda sc, n, d, **k: calls['audio'].append(n) or 1)
        monkeypatch.setattr(
            obs_ws, 'ensure_nested_scene',
            lambda p, c, **k: calls['nested'].append((p, c)) or 9)
        ro._build_audio(1920, 1080, [])
        assert calls['audio'] == [ro.MUSIC_SOURCE_NAME]
        assert calls['nested'] == [], 'nothing to nest into yet'
