"""The DM's second feed: music pushed through vdo.ninja instead of captured
from a local device.

Needed because the local capture only works when OBS sits on the same machine
as the music AND runs Linux — the null sink exists nowhere else. Everything
else has to travel as a stream.
"""
import pytest

from models.ttrpg import tblCharacters


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
def plat(monkeypatch):
    """Pin what OBS can DO, not what it calls itself.

    OBS reports its distro — this project's own box answers "Freedesktop SDK
    25.08 (Flatpak runtime)" — so the transport choice asks whether a
    PulseAudio output capture exists, never whether a string says Linux.
    """
    import routes.obs as ro
    box = {'kind': 'pulse_output_capture'}
    monkeypatch.setattr(ro, 'can_capture_music_device',
                        lambda: box['kind'] == 'pulse_output_capture')
    monkeypatch.setattr(ro, 'lan_base', lambda: 'http://192.168.7.30:8086')
    return box


def _char(**over):
    base = dict(character_id=7, user_id=1, name='Kara', level=1,
                hp_current=5, hp_max=5, created_at='2026-01-01 00:00:00',
                video_stream_id='abc123')
    base.update(over)
    return tblCharacters(**base)


class TestMusicUrls:
    def test_push_carries_proaudio_and_the_device(self, app, settings):
        """&proaudio is what stops echo cancellation, denoise and auto-gain
        from mangling music — they are tuned for speech."""
        import routes.obs as ro
        url = ro.music_push_url()
        assert 'push=' in url
        assert '&proaudio' in url
        assert '&audiodevice=ScenePlay-Music' in url

    def test_push_never_opens_a_camera(self, app, settings):
        """The page promises "music only, no camera or microphone" — but
        &autostart alone also switches on the default webcam. &videodevice=0
        is what actually keeps that promise."""
        import routes.obs as ro
        assert '&videodevice=0' in ro.music_push_url()
        assert 'videodevice' not in ro.music_view_url(), \
            'the viewer captures nothing; the param is a publisher concern'

    def test_push_never_joins_the_table_room(self, app, settings):
        """Players already get the music through the portal; in the room too
        they would hear it twice, out of sync with itself."""
        import routes.obs as ro
        settings['obs_vdo_room'] = 'dungeoncrawler'
        assert 'room=' not in ro.music_push_url()

    def test_view_is_proaudio_and_chromeless(self, app, settings):
        import routes.obs as ro
        url = ro.music_view_url()
        assert 'view=' in url and '&proaudio' in url
        assert '&cleanoutput' in url
        assert 'audiodevice' not in url, 'device choice is a publisher concern'

    def test_stream_id_is_minted_once_and_kept(self, app, settings):
        import routes.obs as ro
        first = ro.music_stream_id()
        assert first and ro.music_stream_id() == first
        assert first != (settings.get('obs_dm_stream_id') or ''), \
            'the music must not share the DM camera id'

    def test_password_rides_along(self, app, settings):
        import routes.obs as ro
        settings['obs_vdo_password'] = 'sesame'
        assert '&password=sesame' in ro.music_push_url()
        assert '&password=sesame' in ro.music_view_url()

    def test_device_label_is_overridable(self, app, settings):
        """Windows and macOS have a virtual cable, not a PipeWire sink."""
        import routes.obs as ro
        settings['obs_music_device_label'] = 'CABLE Output'
        assert '&audiodevice=CABLE%20Output' in ro.music_push_url()


class TestTransportChoice:
    def test_local_linux_obs_captures_the_device(self, app, settings, plat):
        import routes.obs as ro
        settings['obs_host'] = '127.0.0.1'
        assert ro.music_transport() == 'device'

    def test_remote_obs_uses_the_feed(self, app, settings, plat):
        """The null sink exists only on the machine playing the music."""
        import routes.obs as ro
        settings['obs_host'] = '192.168.7.91'
        assert ro.music_transport() == 'feed'

    def test_local_but_no_pulse_capture_uses_the_feed(self, app, settings, plat):
        """A Mac or Windows OBS on this host offers coreaudio/wasapi and could
        never see a PipeWire sink, same host or not."""
        import routes.obs as ro
        settings['obs_host'] = '127.0.0.1'
        plat['kind'] = 'coreaudio_output_capture'
        assert ro.music_transport() == 'feed'

    def test_same_lan_address_counts_as_local(self, app, settings, plat):
        import routes.obs as ro
        settings['obs_host'] = '192.168.7.30'
        assert ro.music_transport() == 'device'

    def test_explicit_choice_overrides_detection(self, app, settings, plat):
        import routes.obs as ro
        settings['obs_host'] = '192.168.7.91'
        settings['obs_music_transport'] = 'device'
        assert ro.music_transport() == 'device'

    def test_music_switched_off_wins(self, app, settings, plat):
        import routes.obs as ro
        settings['obs_music_capture'] = '0'
        assert ro.music_transport() == 'off'


class TestPlaceMusic:
    """Exactly one music source may survive a build."""

    @pytest.fixture()
    def obs(self, monkeypatch, settings):
        import obs_ws
        import routes.obs as ro
        calls = {'audio': [], 'browser': [], 'removed': [], 'placed': []}
        present = {ro.MUSIC_SOURCE_NAME: 1, ro.MUSIC_FEED_SOURCE_NAME: 2}
        monkeypatch.setattr(obs_ws, 'scene_items', lambda n, **k: dict(present))
        monkeypatch.setattr(
            obs_ws, 'ensure_audio_input',
            lambda sc, n, d, **k: calls['audio'].append(n) or 1)
        monkeypatch.setattr(
            obs_ws, 'ensure_browser_input',
            lambda sc, n, u, w, h, **k: calls['browser'].append((n, u)) or (7, []))
        monkeypatch.setattr(
            obs_ws, 'remove_item',
            lambda sc, i, **k: calls['removed'].append(i))
        monkeypatch.setattr(
            obs_ws, 'place_item',
            lambda sc, i, rect, **k: calls['placed'].append(rect))
        monkeypatch.setattr(obs_ws, 'set_item_enabled', lambda *a, **k: None)
        return calls

    def test_device_mode_removes_the_feed(self, app, settings, obs):
        import routes.obs as ro
        ro._place_music('ScenePlay Party', 'device', 1920, [])
        assert obs['audio'] == [ro.MUSIC_SOURCE_NAME]
        assert obs['removed'] == [2], 'the feed source must go'
        assert obs['browser'] == []

    def test_feed_mode_removes_the_device_capture(self, app, settings, obs):
        import routes.obs as ro
        ro._place_music('ScenePlay Party', 'feed', 1920, [])
        assert obs['audio'] == []
        assert obs['removed'] == [1], 'the device capture must go'
        assert obs['browser'] and obs['browser'][0][0] == ro.MUSIC_FEED_SOURCE_NAME
        assert 'view=' in obs['browser'][0][1]

    def test_feed_is_parked_off_canvas(self, app, settings, obs):
        """It has no picture, and a blank frame must not land on the layout."""
        import routes.obs as ro
        ro._place_music('ScenePlay Party', 'feed', 1920, [])
        assert obs['placed'] and obs['placed'][0]['x'] >= 1920

    def test_off_removes_both(self, app, settings, obs):
        import routes.obs as ro
        ro._place_music('ScenePlay Party', 'off', 1920, [])
        assert sorted(obs['removed']) == [1, 2]
        assert obs['audio'] == [] and obs['browser'] == []


class TestDmMicPin:
    """The DM's camera link can pin which microphone vdo.ninja grabs.

    Matters on the machine that also plays the music: a browser that lists
    monitor sources shows the same name twice — once as the mic, once as
    "Monitor of ..." the speakers — and the monitor carries the music and every
    player's voice, straight into the DM's own microphone channel.
    """

    def test_blank_leaves_the_link_alone(self, app, settings):
        import routes.obs as ro
        settings['obs_dm_stream_id'] = 'dmcam'
        assert 'audiodevice' not in ro.dm_tile().video_push_url()

    def test_label_is_pinned_and_encoded(self, app, settings):
        import routes.obs as ro
        settings['obs_dm_stream_id'] = 'dmcam'
        settings['obs_dm_mic_label'] = 'Ryzen HD Audio Controller Analog Stereo'
        url = ro.dm_tile().video_push_url()
        assert '&audiodevice=Ryzen%20HD%20Audio%20Controller%20Analog%20Stereo' in url
        assert 'push=dmcam' in url

    def test_view_link_is_untouched(self, app, settings):
        """Device choice is a publisher concern; OBS just watches."""
        import routes.obs as ro
        settings['obs_dm_stream_id'] = 'dmcam'
        settings['obs_dm_mic_label'] = 'Ryzen'
        assert 'audiodevice' not in ro.dm_tile().video_view_url()

    def test_custom_feed_url_is_not_rewritten(self, app, settings):
        """A DM who pasted their own link owns every parameter in it."""
        import routes.obs as ro
        settings['obs_dm_stream_id'] = 'dmcam'
        settings['obs_dm_feed_url'] = 'https://vdo.ninja/?view=mine'
        settings['obs_dm_mic_label'] = 'Ryzen'
        assert ro.dm_tile().video_push_url() == ''

    def test_the_dm_mic_is_not_the_music_device(self, app, settings):
        """Two separate pushes, two separate devices — pinning one must never
        drag the other along."""
        import routes.obs as ro
        settings['obs_dm_stream_id'] = 'dmcam'
        settings['obs_dm_mic_label'] = 'Ryzen HD Audio Controller Analog Stereo'
        assert 'ScenePlay-Music' not in ro.dm_tile().video_push_url()
        assert 'Ryzen' not in ro.music_push_url()


class TestCapabilityNotPlatformName:
    """Regression: the transport choice must never key off the platform NAME.

    OBS reports its distro. The box this was built on answers "Freedesktop SDK
    25.08 (Flatpak runtime)" — no "Linux" in it — so a name check sent the one
    machine that could capture the sink down the vdo.ninja path instead, and
    silently, because both paths are valid configurations.
    """

    def test_distro_name_without_linux_still_captures_locally(
            self, app, settings, monkeypatch):
        import obs_ws
        import routes.obs as ro
        settings['obs_host'] = '127.0.0.1'
        monkeypatch.setattr(ro, 'lan_base', lambda: 'http://192.168.7.30:8086')
        monkeypatch.setattr(obs_ws, 'audio_capture_kind',
                            lambda: 'pulse_output_capture')
        monkeypatch.setattr(
            obs_ws, 'current_state',
            lambda: {'obs_platform': 'Freedesktop SDK 25.08 (Flatpak runtime)'})
        assert ro.music_transport() == 'device'

    def test_no_capture_kind_at_all_falls_back_to_the_feed(
            self, app, settings, monkeypatch):
        """A build with no audio-capture plugin must not be handed a device."""
        import obs_ws
        import routes.obs as ro
        settings['obs_host'] = '127.0.0.1'
        monkeypatch.setattr(ro, 'lan_base', lambda: 'http://192.168.7.30:8086')
        monkeypatch.setattr(obs_ws, 'audio_capture_kind', lambda: None)
        assert ro.music_transport() == 'feed'


class TestTableRoom:
    """The room is created for the table, and its name is the way in."""

    def test_new_room_fits_what_vdo_ninja_accepts(self, app, settings):
        """vdo.ninja rejects a name over 30 chars or with punctuation in it —
        and it rejects it at the GUEST, so it looks like the player's link is
        broken rather than the setting being wrong."""
        import routes.obs as ro
        r = ro._new_room_name()
        assert 0 < len(r) <= ro.ROOM_MAX, len(r)
        assert r.isalnum(), r
        assert r != ro._new_room_name(), 'a fresh room every time'

    def test_room_is_unguessable(self, app, settings):
        """The name IS the credential — a vdo.ninja room exists as soon as
        someone joins it, so a guessable name is an open door to the table."""
        import routes.obs as ro
        rooms = {ro._new_room_name() for _ in range(200)}
        assert len(rooms) == 200, 'collisions mean predictability'

    def test_creating_a_room_puts_everyone_in_it(self, app, settings):
        import routes.obs as ro
        settings['obs_vdo_room'] = ro._new_room_name()
        settings['obs_dm_stream_id'] = 'dmcam'
        room = settings['obs_vdo_room']
        assert '&room=' + room in _char().video_push_url()
        assert '&room=' + room in ro.dm_tile().video_push_url(), \
            'the DM has to be in the room too, or nobody hears them'

    def test_the_music_push_stays_out_of_the_room(self, app, settings):
        """Players already get the music from the portal; in the room as well
        they would hear it twice, drifting against itself."""
        import routes.obs as ro
        settings['obs_vdo_room'] = ro._new_room_name()
        assert 'room=' not in ro.music_push_url()


class TestRoomNameCleaning:
    """A name vdo.ninja will not take is a broken session, not a typo."""

    def test_punctuation_is_stripped(self, app, settings):
        import routes.obs as ro
        assert ro.clean_room('my-table room!') == 'mytableroom'

    def test_over_length_is_trimmed(self, app, settings):
        import routes.obs as ro
        out = ro.clean_room('a' * 60)
        assert len(out) == ro.ROOM_MAX

    def test_already_valid_is_untouched(self, app, settings):
        import routes.obs as ro
        assert ro.clean_room('dungeoncrawler') == 'dungeoncrawler'

    def test_generated_rooms_survive_cleaning(self, app, settings):
        """Whatever the generator emits must already be acceptable, or the
        Create button would hand out a name the guests reject."""
        import routes.obs as ro
        for _ in range(50):
            r = ro._new_room_name()
            assert ro.clean_room(r) == r


class TestRelayLearnsTheRoom:
    """The portal carries the link ScenePlay builds, so it has to be told when
    that link changes. An un-pushed room is worse than a broken one: the old
    link still works, into a room nobody else is in."""

    @pytest.fixture()
    def pushed(self, monkeypatch):
        import relay_broadcaster as rb
        calls = []
        monkeypatch.setattr(rb, 'push_character_feeds',
                            lambda: calls.append(1))
        return calls

    def test_repush_is_called(self, app, settings, pushed):
        import routes.obs as ro
        ro.repush_feeds('test')
        assert pushed == [1]

    def test_a_dead_relay_never_breaks_the_caller(self, app, settings,
                                                  monkeypatch):
        """The relay is usually off; that must not fail a room change."""
        import relay_broadcaster as rb
        import routes.obs as ro

        def boom():
            raise RuntimeError('relay unreachable')
        monkeypatch.setattr(rb, 'push_character_feeds', boom)
        ro.repush_feeds('test')          # must not raise

    def test_the_pushed_link_carries_the_room(self, app, settings):
        """What the portal receives is the finished URL, room included — the
        relay is never told the room separately."""
        import routes.obs as ro
        settings['obs_vdo_room'] = ro._new_room_name()
        url = _char().video_push_url()
        assert 'room=' + settings['obs_vdo_room'] in url
