"""Where OBS fetches ScenePlay's pages from, and noticing when it goes stale.

Getting this wrong is invisible: OBS connects over the websocket perfectly and
then renders every source blank. A DHCP lease moving this machine to a new
address does exactly that, silently, to a setup that worked yesterday.
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


@pytest.fixture()
def lan(monkeypatch):
    """Pin the detected LAN address so tests don't depend on the host."""
    import routes.obs as ro
    monkeypatch.setattr(ro, 'lan_base', lambda: 'http://192.168.7.30:8086')


class TestSuggestedBase:
    def test_prefers_the_address_the_dm_is_browsing_on(self, app, settings,
                                                       lan):
        """It carries the real port; lan_base can only assume the default."""
        import routes.obs as ro
        with app.test_request_context(base_url='http://192.168.7.55:9000'):
            assert ro.suggested_card_base() == 'http://192.168.7.55:9000'

    def test_loopback_browsing_falls_back_to_the_lan_address(self, app,
                                                             settings, lan):
        """Baking in localhost works here and renders blank everywhere else."""
        import routes.obs as ro
        for url in ('http://localhost:8086', 'http://127.0.0.1:8086'):
            with app.test_request_context(base_url=url):
                assert ro.suggested_card_base() == 'http://192.168.7.30:8086'

    def test_no_request_context_still_answers(self, app, settings, lan):
        """Called from the auto-return timer, which has no request."""
        import routes.obs as ro
        assert ro.suggested_card_base() == 'http://192.168.7.30:8086'


class TestStaleDetection:
    def test_ip_that_no_longer_matches_is_stale(self, app, settings, lan):
        import routes.obs as ro
        settings['obs_card_base'] = 'http://192.168.7.30:8086'
        assert ro.card_base_stale() is False
        settings['obs_card_base'] = 'http://192.168.7.99:8086'
        assert ro.card_base_stale() is True

    def test_a_different_port_on_the_same_ip_is_not_stale(self, app, settings,
                                                          lan):
        """lan_base only guesses the port — it must not second-guess a DM
        running ScenePlay somewhere else."""
        import routes.obs as ro
        settings['obs_card_base'] = 'http://192.168.7.30:9999'
        assert ro.card_base_stale() is False

    def test_hostnames_are_never_called_stale(self, app, settings, lan):
        """An mDNS or DNS name may resolve perfectly well; nagging about it
        every visit would train the DM to ignore the warning."""
        import routes.obs as ro
        for base in ('http://sceneplay.local:8086', 'http://gm-box:8086'):
            settings['obs_card_base'] = base
            assert ro.card_base_stale() is False

    def test_loopback_is_left_to_its_own_warning(self, app, settings, lan):
        import routes.obs as ro
        settings['obs_card_base'] = 'http://127.0.0.1:8086'
        assert ro.card_base_stale() is False

    def test_unset_is_not_stale(self, app, settings, lan):
        import routes.obs as ro
        assert ro.card_base_stale() is False

    def test_undetectable_lan_never_reports_stale(self, app, settings,
                                                  monkeypatch):
        """With no route out, lan_base falls back to loopback. Warning then
        would be pure noise on a machine that is working fine."""
        import routes.obs as ro
        monkeypatch.setattr(ro, 'lan_base', lambda: 'http://127.0.0.1:8086')
        settings['obs_card_base'] = 'http://192.168.7.30:8086'
        assert ro.card_base_stale() is False
