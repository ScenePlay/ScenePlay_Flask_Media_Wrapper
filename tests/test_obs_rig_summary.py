"""What running OBS locally vs remotely actually costs, in one place.

Each consequence below is invisible in the moment it bites — a blank source, a
silent channel — and every one is decided by the same question, so they are
answered together rather than scattered across the page.
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
def rig(monkeypatch):
    """Pin the machine and what OBS reports about itself."""
    import obs_ws
    import routes.obs as ro
    box = {'platform': 'Freedesktop SDK 25.08 (Flatpak runtime)',
           'kind': 'pulse_output_capture'}
    monkeypatch.setattr(ro, 'lan_base', lambda: 'http://192.168.7.30:8086')
    monkeypatch.setattr(obs_ws, 'current_state',
                        lambda: {'obs_platform': box['platform']})
    monkeypatch.setattr(obs_ws, 'audio_capture_kind', lambda: box['kind'])
    return box


class TestLocalRig:
    def test_local_monitors_the_device(self, app, settings, rig):
        import routes.obs as ro
        settings['obs_host'] = '127.0.0.1'
        settings['obs_card_base'] = 'http://192.168.7.30:8086'
        s = ro.rig_summary()
        assert s['local'] is True
        assert s['transport'] == 'device'
        assert s['problems'] == []
        assert s['steps'] == [], 'a local rig needs no standing chores'

    def test_loopback_page_address_is_fine_locally(self, app, settings, rig):
        """Only a REMOTE OBS is broken by localhost."""
        import routes.obs as ro
        settings['obs_host'] = '127.0.0.1'
        settings['obs_card_base'] = 'http://127.0.0.1:8086'
        assert ro.rig_summary()['problems'] == []


class TestRemoteRig:
    def test_remote_streams_the_music_and_says_so(self, app, settings, rig):
        import routes.obs as ro
        settings['obs_host'] = '192.168.7.91'
        settings['obs_card_base'] = 'http://192.168.7.30:8086'
        s = ro.rig_summary()
        assert s['local'] is False
        assert s['transport'] == 'feed'
        assert any('music feed' in x.lower() for x in s['steps'])

    def test_loopback_page_address_is_flagged_as_a_problem(self, app, settings,
                                                           rig):
        """THE invisible failure: OBS connects fine and renders nothing."""
        import routes.obs as ro
        settings['obs_host'] = '192.168.7.91'
        settings['obs_card_base'] = 'http://localhost:8086'
        s = ro.rig_summary()
        assert s['problems'], 'must not stay silent about this'
        assert 'blank' in s['problems'][0]
        assert '192.168.7.30' in s['problems'][0], 'must name the fix'

    def test_macos_browser_audio_is_called_out(self, app, settings, rig):
        import routes.obs as ro
        settings['obs_host'] = '192.168.7.91'
        settings['obs_card_base'] = 'http://192.168.7.30:8086'
        rig['platform'] = 'macOS Tahoe (26.5.2)'
        rig['kind'] = 'coreaudio_output_capture'
        s = ro.rig_summary()
        assert any('macos' in p.lower() for p in s['problems'])

    def test_a_linux_rig_is_not_accused_of_being_a_mac(self, app, settings,
                                                       rig):
        import routes.obs as ro
        settings['obs_host'] = '192.168.7.91'
        settings['obs_card_base'] = 'http://192.168.7.30:8086'
        assert not any('macos' in p.lower() for p in ro.rig_summary()['problems'])


class TestMusicOff:
    def test_off_is_explained_not_left_blank(self, app, settings, rig):
        import routes.obs as ro
        settings['obs_host'] = '127.0.0.1'
        settings['obs_music_capture'] = '0'
        s = ro.rig_summary()
        assert s['transport'] == 'off'
        assert s['music_why'], 'a disabled path still needs a sentence'


class TestNoContradictoryAdvice:
    def test_steps_never_quote_the_address_it_just_rejected(
            self, app, settings, rig):
        """Telling the DM to fix the loopback address and then to keep that
        same address reachable is advice that argues with itself."""
        import routes.obs as ro
        settings['obs_host'] = '192.168.7.91'
        settings['obs_card_base'] = 'http://localhost:8086'
        s = ro.rig_summary()
        joined = ' '.join(s['steps'])
        assert 'localhost' not in joined
        assert '192.168.7.30' in joined, 'should name the address that works'

    def test_a_good_remote_address_is_quoted_as_is(self, app, settings, rig):
        import routes.obs as ro
        settings['obs_host'] = '192.168.7.91'
        settings['obs_card_base'] = 'http://192.168.7.30:9000'
        assert '192.168.7.30:9000' in ' '.join(ro.rig_summary()['steps'])


class TestCustomUrlLeavesPlayersOutside:
    """A custom feed URL is a link ScenePlay does not build, so the room never
    reaches it. That player publishes outside the room — silently, because
    their own camera page looks perfectly normal to them."""

    def _party(self, monkeypatch, chars):
        import routes.obs as ro
        monkeypatch.setattr(ro, '_active_party', lambda: chars)

    def test_a_custom_url_player_is_named(self, app, settings, rig,
                                          monkeypatch):
        import routes.obs as ro
        from models.ttrpg import tblCharacters
        settings['obs_host'] = '127.0.0.1'
        settings['obs_vdo_room'] = 'abc123'
        carl = tblCharacters(character_id=1, user_id=1, name='Carl', level=1,
                             hp_current=1, hp_max=1,
                             created_at='2026-01-01 00:00:00',
                             video_feed_url='https://vdo.ninja/?view=X')
        self._party(monkeypatch, [carl])
        s = ro.rig_summary()
        assert any('Carl' in p for p in s['problems'])

    def test_nothing_said_when_everyone_is_managed(self, app, settings, rig,
                                                   monkeypatch):
        import routes.obs as ro
        from models.ttrpg import tblCharacters
        settings['obs_host'] = '127.0.0.1'
        settings['obs_vdo_room'] = 'abc123'
        ok = tblCharacters(character_id=2, user_id=1, name='Donut', level=1,
                           hp_current=1, hp_max=1,
                           created_at='2026-01-01 00:00:00',
                           video_stream_id='xyz', video_feed_url='')
        self._party(monkeypatch, [ok])
        assert ro.rig_summary()['problems'] == []

    def test_silent_when_there_is_no_room(self, app, settings, rig,
                                          monkeypatch):
        """Without a room a custom URL is a legitimate choice, not a fault."""
        import routes.obs as ro
        from models.ttrpg import tblCharacters
        settings['obs_host'] = '127.0.0.1'
        carl = tblCharacters(character_id=1, user_id=1, name='Carl', level=1,
                             hp_current=1, hp_max=1,
                             created_at='2026-01-01 00:00:00',
                             video_feed_url='https://vdo.ninja/?view=X')
        self._party(monkeypatch, [carl])
        assert ro.rig_summary()['problems'] == []
