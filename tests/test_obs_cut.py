"""Scene targets behind the sidebar's cut buttons.

Unit level, matching the rest of this suite: the app fixture is a bare Flask
app with no blueprints, so the HTTP layer is exercised against a running
server rather than here. What is worth pinning down in isolation is the
mapping from a button to a scene name — get that wrong and a button silently
cuts to the wrong thing, or two buttons light up for one scene."""
import pytest

from routes.obs import CUT_TARGETS, _cut_scene_name


@pytest.fixture()
def settings(app, monkeypatch):
    """routes.obs holds its own appsettingGet from `from sql import ...`."""
    store = {}
    import routes.obs as ro
    import sql
    get = lambda name, default=None: store.get(name, default)     # noqa: E731
    for mod in (sql, ro):
        monkeypatch.setattr(mod, 'appsettingGet', get, raising=False)
    return store


class TestCutTargets:
    def test_the_expected_targets_exist(self):
        assert set(CUT_TARGETS) == {'map', 'pre', 'intermission', 'post', 'party'}

    def test_every_target_resolves_to_a_scene_name(self, app, settings):
        for key in CUT_TARGETS:
            name = _cut_scene_name(key)
            assert name and isinstance(name, str), key

    def test_targets_are_distinct_scenes(self, app, settings):
        """Two targets sharing a scene would light two buttons for one cut."""
        names = [_cut_scene_name(k) for k in CUT_TARGETS]
        assert len(set(names)) == len(names), names

    def test_defaults_are_the_sceneplay_scenes(self, app, settings):
        assert _cut_scene_name('map') == 'ScenePlay Map'
        assert _cut_scene_name('party') == 'ScenePlay Party'
        assert _cut_scene_name('pre') == 'ScenePlay Pre'
        assert _cut_scene_name('post') == 'ScenePlay Post'
        assert _cut_scene_name('intermission') == 'ScenePlay Intermission'

    @pytest.mark.parametrize('key,setting', [
        ('map', 'obs_map_scene'),
        ('party', 'obs_party_scene'),
        ('pre', 'obs_pre_scene'),
        ('intermission', 'obs_intermission_scene'),
        ('post', 'obs_post_scene'),
    ])
    def test_a_renamed_scene_is_honoured(self, app, settings, key, setting):
        """The DM can point a target at a scene of their own naming."""
        settings[setting] = 'My Own Scene'
        assert _cut_scene_name(key) == 'My Own Scene'

    def test_blank_setting_falls_back_to_the_default(self, app, settings):
        """A blank row is not 'absent' — the coercion has to catch it, or the
        button would try to cut to an empty scene name."""
        settings['obs_map_scene'] = '   '
        assert _cut_scene_name('map') == 'ScenePlay Map'
