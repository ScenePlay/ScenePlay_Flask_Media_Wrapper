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


class TestShowSceneTitleStrip:
    """The campaign banner rides the pre/intermission/post cards too — the
    SAME title input at the SAME rect the party and map scenes use, so a cut
    to a card never jumps or drops the title."""

    @pytest.fixture()
    def rig(self, app, settings, monkeypatch):
        import obs_ws
        import routes.obs as ro
        settings['obs_panel_on'] = '1'
        made, placed, raised = {}, [], []

        def fake_ensure(scene, source, url, w, h, **_k):
            made[(scene, source)] = len(made) + 1
            return made[(scene, source)], []

        monkeypatch.setattr(obs_ws, 'current_state',
                            lambda: {'base_width': 1920, 'base_height': 1080})
        monkeypatch.setattr(obs_ws, 'ensure_scene', lambda s: None)
        monkeypatch.setattr(obs_ws, 'ensure_browser_input', fake_ensure)
        monkeypatch.setattr(obs_ws, 'place_item',
                            lambda sc, iid, box: placed.append((sc, iid, box)))
        monkeypatch.setattr(obs_ws, 'set_item_enabled', lambda *a: None)
        monkeypatch.setattr(obs_ws, 'scene_list',
                            lambda refresh=False: [])
        monkeypatch.setattr(ro, '_raise_to_front',
                            lambda sc, iid, w: raised.append((sc, iid)))
        monkeypatch.setattr(ro, '_place_background', lambda *a, **k: None)
        monkeypatch.setattr(ro, '_upsert_special_map', lambda *a, **k: None)
        monkeypatch.setattr(ro, 'panel_url', lambda mode='info': f'u:{mode}')
        return ro, made, placed, raised

    def test_the_strip_rides_every_card_scene(self, rig):
        import obs_layout
        ro, made, placed, raised = rig
        scenes, warnings = ro.ensure_show_scenes()
        assert warnings == []
        want = obs_layout.frame_areas(
            1920, 1080, ro.panel_side(), ro.panel_fraction(),
            title_h=ro.title_height(), panel_on=True)['title']
        for scene in scenes.values():
            iid = made.get((scene, ro.TITLE_SOURCE_NAME))
            assert iid, f'{scene} is missing the title strip'
            box = next(b for sc, i, b in placed if (sc, i) == (scene, iid))
            assert (box['x'], box['y'], box['w'], box['h']) == (
                want[0], want[1], want[2], want[3])
            assert (scene, iid) in raised, \
                'a reused strip keeps its z-order and hides under the card'

    def test_a_zero_height_strip_is_left_out(self, rig, settings):
        """obs_title_h of 0 hides the strip everywhere else; the cards must
        follow, not pin a zero-height page to the canvas."""
        ro, made, _placed, _raised = rig
        settings['obs_title_h'] = '0'
        scenes, _warnings = ro.ensure_show_scenes()
        for scene in scenes.values():
            assert (scene, ro.TITLE_SOURCE_NAME) not in made
