"""Auto-return: nothing holds one character on screen forever.

Two separate holds can strand a session on one person — the enlarged tile in
the party scene, and the battle map pinned to that character's eyes. The
setting says "everyone on screen", so both have to let go.
"""
import pytest


@pytest.fixture()
def settings(app, monkeypatch):
    store = {}
    import routes.obs as ro
    import sql
    fake = lambda name, default=None: store.get(name, default)   # noqa: E731
    sets = lambda name, value: store.__setitem__(name, value)    # noqa: E731
    monkeypatch.setattr(sql, 'appsettingGet', fake)
    monkeypatch.setattr(ro, 'appsettingGet', fake)
    monkeypatch.setattr(ro, 'appsettingSet', sets)
    return store


@pytest.fixture()
def armed(monkeypatch):
    """Record what the auto-return clock was asked to do."""
    import routes.obs as ro
    calls = {'scheduled': [], 'cancelled': 0}
    monkeypatch.setattr(ro, '_schedule_return',
                        lambda app_obj, secs: calls['scheduled'].append(secs))
    monkeypatch.setattr(ro, '_cancel_return',
                        lambda: calls.__setitem__('cancelled',
                                                  calls['cancelled'] + 1))
    monkeypatch.setattr(ro, '_special_scene', lambda key: 'ScenePlay Party')
    return calls


class TestArming:
    def test_featuring_a_player_starts_the_clock(self, app, settings, armed):
        import routes.obs as ro
        settings['obs_auto_return_s'] = '10'
        with app.test_request_context():
            ro._after_switch('')          # '' == "we featured, nothing was cut"
        assert armed['scheduled'] == [10]

    def test_zero_seconds_means_never(self, app, settings, armed):
        import routes.obs as ro
        settings['obs_auto_return_s'] = '0'
        with app.test_request_context():
            ro._after_switch('')
        assert armed['scheduled'] == []
        assert armed['cancelled'] == 1

    def test_cutting_to_the_group_shot_disarms(self, app, settings, armed):
        """Already home — there is nothing to drift back to."""
        import routes.obs as ro
        settings['obs_auto_return_s'] = '10'
        with app.test_request_context():
            ro._after_switch('ScenePlay Party')
        assert armed['scheduled'] == []

    def test_a_junk_setting_does_not_arm(self, app, settings, armed):
        import routes.obs as ro
        settings['obs_auto_return_s'] = 'soon'
        with app.test_request_context():
            ro._after_switch('')
        assert armed['scheduled'] == []


class TestReleasesBothHolds:
    def test_unfeature_releases_the_map_pin_too(self, app, settings,
                                                monkeypatch):
        """The tile used to level while the battle map went on staring through
        whoever it was pinned to — half a return."""
        import obs_ws
        import routes.obs as ro
        settings['obs_featured_id'] = '5'
        settings['obs_view_char'] = '5'
        monkeypatch.setattr(ro, '_sync_party_scene', lambda **k: {'warnings': []})
        monkeypatch.setattr(ro, '_special_scene', lambda key: 'ScenePlay Party')
        monkeypatch.setattr(ro, '_cancel_return', lambda: None)
        monkeypatch.setattr(obs_ws, 'current_state',
                            lambda: {'current_scene': 'ScenePlay Party'})
        monkeypatch.setattr(obs_ws, 'switch_scene', lambda *a, **k: None)
        ro._unfeature()
        assert settings.get('obs_featured_id') in ('', None)
        assert settings.get('obs_view_char') in ('', None), \
            'the map was left pinned to one character'
