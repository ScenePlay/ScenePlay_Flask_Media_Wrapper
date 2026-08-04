"""Marking which ScenePlay scenes also drive an OBS scene.

Two states have to be distinguishable, because they look identical from the
scene list and one of them cost a whole debugging session: a scene mapped to
an OBS scene and armed, versus one mapped but inert because the Scene Links
switch is off.
"""
import pytest

from extensions import db
from models.ttrpg import tblObsSceneMap


@pytest.fixture()
def settings(app, monkeypatch):
    store = {}
    import routes.obs as ro
    import sql
    fake = lambda name, default=None: store.get(name, default)   # noqa: E731
    monkeypatch.setattr(sql, 'appsettingGet', fake)
    monkeypatch.setattr(ro, 'appsettingGet', fake)
    return store


def _map(scene_id, obs_scene, kind='scene'):
    db.session.add(tblObsSceneMap(entity_type=kind, entity_id=scene_id,
                                  entity_key='', scene_name=obs_scene,
                                  source_name='', auto_created=0,
                                  sort_order=0,
                                  updated_at='2026-01-01 00:00:00'))
    db.session.commit()


class TestSceneLinkMap:
    def test_lists_only_scene_mappings(self, app, settings):
        """Player tiles and the special map/pre/post rows live in the same
        table and must not show up as scene links."""
        import routes.obs as ro
        _map(25, 'ScenePlay Pre')
        _map(26, 'ScenePlay Post')
        _map(7, 'ScenePlay Party', kind='player')
        _map(0, 'ScenePlay Map', kind='special')
        assert ro.scene_link_map() == {25: 'ScenePlay Pre',
                                       26: 'ScenePlay Post'}

    def test_blank_target_is_not_a_link(self, app, settings):
        """A row with no OBS scene would render a marker that does nothing."""
        import routes.obs as ro
        _map(25, '')
        assert ro.scene_link_map() == {}

    def test_empty_when_nothing_is_mapped(self, app, settings):
        import routes.obs as ro
        assert ro.scene_link_map() == {}


class TestLinksLive:
    def test_needs_both_switches(self, app, settings):
        """Mapped-and-armed vs mapped-and-inert is the whole distinction."""
        import routes.obs as ro
        assert ro.scene_links_live() is False
        settings['obs_enabled'] = '1'
        assert ro.scene_links_live() is False, 'scene linking still off'
        settings['obs_scene_link'] = '1'
        assert ro.scene_links_live() is True

    def test_obs_disabled_beats_scene_link(self, app, settings):
        """Scene linking on while OBS control is off cuts nothing."""
        import routes.obs as ro
        settings['obs_scene_link'] = '1'
        settings['obs_enabled'] = '0'
        assert ro.scene_links_live() is False
