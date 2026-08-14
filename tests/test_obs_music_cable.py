"""The Windows half of the music feed: a virtual cable, named at both ends.

Linux builds its own capture sink and points mpv at it, so the feed path needs
no setup there at all. Windows can build nothing: no sink, no monitor source,
and no way for a browser to capture a speaker output. The music therefore has
to be ROUTED — mpv plays into a virtual cable's input, the vdo.ninja push tab
captures its output — and until it is, every visible part of the integration
is correct and the stream is silent. The OBS source exists, unmuted, on a live
browser page publishing nothing.

That failure is what these tests are about: the two ends of the cable, and the
warnings that say so when either is missing.
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
def mpv(monkeypatch):
    """mpv's device list, with the probe cache emptied around each test.

    The platform is pinned to "needs a cable" — on any other the probe is
    skipped entirely (Linux hides the control), and these tests must describe
    Windows wherever the suite happens to run."""
    import subprocess
    import routes.obs as ro
    monkeypatch.setattr(ro, 'music_cable_platform', lambda: True)
    box = {'out': (
        "List of detected audio devices:\n"
        "  'auto' (Autoselect device)\n"
        "  'wasapi/{5072e9b8-0f31}' (Speakers (Realtek(R) Audio))\n"
        "  'wasapi/{6e659a59-72eb}' (CABLE In 16ch (VB-Audio Virtual Cable))\n"
        "  'wasapi/{d4d12d54-8896}' (CABLE Input (VB-Audio Virtual Cable))\n"
        "  'openal' (Default (openal))\n"), 'calls': 0}

    class _Res:
        def __init__(self, out):
            self.stdout, self.returncode = out, 0

    def fake_run(cmd, **kw):
        box['calls'] += 1
        if isinstance(box['out'], Exception):
            raise box['out']
        return _Res(box['out'])

    monkeypatch.setattr(subprocess, 'run', fake_run)
    monkeypatch.setattr(ro, '_MPV_DEVICES', {'at': 0.0, 'list': []})
    return box


CABLE = 'wasapi/{d4d12d54-8896}'


class TestDeviceList:
    def test_reads_the_devices_mpv_itself_reports(self, app, settings, mpv):
        """The value in the box is an mpv --audio-device id, and mpv's WASAPI
        ids are opaque GUIDs — nobody can type one from a sound panel."""
        import routes.obs as ro
        opts = dict(ro.music_output_choices(refresh=True))
        assert opts[CABLE] == 'CABLE Input (VB-Audio Virtual Cable)'
        assert opts['wasapi/{5072e9b8-0f31}'] == 'Speakers (Realtek(R) Audio)'

    def test_default_is_first_and_blank(self, app, settings, mpv):
        import routes.obs as ro
        first = ro.music_output_choices(refresh=True)[0]
        assert first[0] == '', 'unset must mean "mpv picks", as before'

    def test_the_16ch_twin_is_flagged(self, app, settings, mpv):
        """"CABLE In 16ch" sits four characters from "CABLE Input" in the
        same list, and picking it is a silently dead feed (its audio never
        reaches the stereo CABLE Output). The warning must live on the
        option itself — a help-text footnote was already there the day this
        cost a working feed."""
        import routes.obs as ro
        opts = dict(ro.music_output_choices(refresh=True))
        assert 'wrong end' in opts['wasapi/{6e659a59-72eb}']
        assert 'wrong end' not in opts['wasapi/{d4d12d54-8896}']

    def test_auto_is_not_offered_twice(self, app, settings, mpv):
        """mpv's own 'auto' means what the blank entry already means; two ways
        to say it read as two different choices."""
        import routes.obs as ro
        assert 'auto' not in dict(ro.music_output_choices(refresh=True))

    def test_probe_is_cached(self, app, settings, mpv):
        """This is asked on every Broadcast render, and the list changes only
        when someone installs a driver."""
        import routes.obs as ro
        ro.music_output_choices(refresh=True)
        ro.music_output_choices()
        ro.music_output_choices()
        assert mpv['calls'] == 1

    def test_missing_mpv_still_offers_the_default(self, app, settings, mpv):
        import routes.obs as ro
        mpv['out'] = OSError('mpv not found')
        assert ro.music_output_choices(refresh=True) == [
            ('', 'Default output device')]

    def test_saved_device_survives_a_failed_probe(self, app, settings, mpv):
        """The page autosaves. If an undetected device dropped out of the
        select, merely OPENING the page would post "default" back and take the
        music off the cable — silence, caused by looking at the settings."""
        import routes.obs as ro
        settings['music_output_device'] = CABLE
        mpv['out'] = OSError('mpv not found')
        opts = ro.music_output_choices(refresh=True)
        assert CABLE not in dict(opts)
        assert CABLE in dict(ro.music_output_options())

    def test_detected_device_is_not_listed_twice(self, app, settings, mpv):
        import routes.obs as ro
        settings['music_output_device'] = CABLE
        ro.music_output_choices(refresh=True)
        ids = [d for d, _ in ro.music_output_options()]
        assert ids.count(CABLE) == 1

    def test_linux_never_spawns_the_probe(self, app, settings, mpv,
                                          monkeypatch):
        """Linux builds its own sink and never shows the control — but the
        cfg dict still asks. That must not cost a subprocess per render."""
        import routes.obs as ro
        monkeypatch.setattr(ro, 'music_cable_platform', lambda: False)
        assert ro.music_output_choices(refresh=True) == [
            ('', 'Default output device')]
        assert mpv['calls'] == 0


FFMPEG_DSHOW = (
    '[dshow @ 0x1] "Integrated Camera" (video)\n'
    '[dshow @ 0x1]   Alternative name "@device_pnp_x"\n'
    '[dshow @ 0x1] "Microphone Array (Realtek(R) Audio)" (audio)\n'
    '[dshow @ 0x1] "CABLE Output (VB-Audio Virtual Cable)" (audio)\n'
    'Error opening input file dummy.\n')


class TestCaptureSuggestions:
    """The vdo.ninja label box offers this machine's capture devices, so the
    DM picks "CABLE Output (...)" from a list instead of transcribing it."""

    @pytest.fixture()
    def ffprobe(self, monkeypatch):
        import subprocess
        import routes.obs as ro
        monkeypatch.setattr(ro, 'music_cable_platform', lambda: True)
        monkeypatch.setattr(ro, '_CAPTURE_DEVICES', {'at': 0.0, 'list': []})
        box = {'err': FFMPEG_DSHOW, 'calls': 0}

        class _Res:
            def __init__(self):
                self.stdout, self.stderr, self.returncode = '', box['err'], 1

        def fake_run(cmd, **kw):
            box['calls'] += 1
            if isinstance(box['err'], Exception):
                raise box['err']
            return _Res()
        monkeypatch.setattr(subprocess, 'run', fake_run)
        return box

    def test_audio_devices_only(self, app, settings, ffprobe):
        """Cameras are in the same listing; suggesting one would send the
        push tab hunting for sound on a webcam."""
        import routes.obs as ro
        assert ro.music_capture_choices(refresh=True) == [
            'Microphone Array (Realtek(R) Audio)',
            'CABLE Output (VB-Audio Virtual Cable)']

    def test_probe_failure_keeps_the_last_good_list(self, app, settings,
                                                    ffprobe):
        import routes.obs as ro
        good = ro.music_capture_choices(refresh=True)
        ffprobe['err'] = OSError('ffmpeg not found')
        assert ro.music_capture_choices(refresh=True) == good

    def test_probe_is_cached(self, app, settings, ffprobe):
        import routes.obs as ro
        ro.music_capture_choices(refresh=True)
        ro.music_capture_choices()
        assert ffprobe['calls'] == 1

    def test_linux_gets_no_windows_suggestions(self, app, settings, ffprobe,
                                               monkeypatch):
        """The one right answer there is the ScenePlay-Music source the app
        builds — a list of dshow names could only mislead."""
        import shutil
        import routes.obs as ro
        monkeypatch.setattr(ro, 'music_cable_platform', lambda: False)
        monkeypatch.setattr(shutil, 'which', lambda cmd: '/usr/bin/pactl')
        choices = ro.music_capture_choices(refresh=True)
        assert 'CABLE Output (VB-Audio Virtual Cable)' not in choices
        assert choices[0] == ro.DEFAULT_MUSIC_LABEL


PACTL_SOURCES = (
    'Source #54\n'
    '\tState: SUSPENDED\n'
    '\tName: alsa_output.pci-0000_00_1f.3.analog-stereo.monitor\n'
    '\tDescription: Monitor of Built-in Audio Analog Stereo\n'
    'Source #55\n'
    '\tState: RUNNING\n'
    '\tName: alsa_input.pci-0000_00_1f.3.analog-stereo\n'
    '\tDescription: Built-in Audio Analog Stereo\n'
    'Source #56\n'
    '\tState: IDLE\n'
    '\tName: sceneplay_music\n'
    '\tDescription: ScenePlay-Music\n'
    'Source #57\n'
    '\tState: IDLE\n'
    '\tName: sceneplay_stream.monitor\n'
    '\tDescription: Monitor of ScenePlay-Stream\n')


class TestLinuxSuggestions:
    """The same box on Linux. The right answer is the source the app builds
    itself, and remembering its exact name is not a thing to ask of anyone —
    it must be in the list, and it must be first."""

    @pytest.fixture()
    def pactl(self, monkeypatch):
        import shutil
        import subprocess
        import routes.obs as ro
        monkeypatch.setattr(ro, 'music_cable_platform', lambda: False)
        monkeypatch.setattr(ro, '_CAPTURE_DEVICES', {'at': 0.0, 'list': []})
        monkeypatch.setattr(
            shutil, 'which',
            lambda cmd: '/usr/bin/pactl' if cmd == 'pactl' else None)
        box = {'out': PACTL_SOURCES, 'calls': 0}

        class _Res:
            def __init__(self):
                self.stdout, self.stderr, self.returncode = box['out'], '', 0

        def fake_run(cmd, **kw):
            box['calls'] += 1
            if isinstance(box['out'], Exception):
                raise box['out']
            return _Res()
        monkeypatch.setattr(subprocess, 'run', fake_run)
        return box

    def test_the_app_built_source_leads(self, app, settings, pactl):
        import routes.obs as ro
        choices = ro.music_capture_choices(refresh=True)
        assert choices[0] == ro.DEFAULT_MUSIC_LABEL
        assert choices.count(ro.DEFAULT_MUSIC_LABEL) == 1, \
            'pactl reports the source too; once is enough'

    def test_real_inputs_are_still_offered(self, app, settings, pactl):
        """Someone routing music through a real interface can still pick it."""
        import routes.obs as ro
        assert 'Built-in Audio Analog Stereo' in \
            ro.music_capture_choices(refresh=True)

    def test_monitors_are_not_suggested(self, app, settings, pactl):
        """"Monitor of <your speakers>" captures the players and loops them
        back; the safe one carries the same audio ScenePlay-Music already
        does. Neither is worth offering."""
        import routes.obs as ro
        assert not any(c.startswith('Monitor of ')
                       for c in ro.music_capture_choices(refresh=True))

    def test_a_dead_probe_still_offers_the_default(self, app, settings,
                                                   pactl):
        """The remap source only exists once music has played, and pactl can
        be missing entirely — the one right answer stays in the box."""
        import routes.obs as ro
        pactl['out'] = OSError('pactl went away')
        assert ro.music_capture_choices(refresh=True) == [
            ro.DEFAULT_MUSIC_LABEL]

    def test_probe_failure_keeps_the_last_good_list(self, app, settings,
                                                    pactl):
        import routes.obs as ro
        good = ro.music_capture_choices(refresh=True)
        pactl['out'] = OSError('pactl went away')
        assert ro.music_capture_choices(refresh=True) == good

    def test_no_pactl_no_suggestions(self, app, settings, pactl, monkeypatch):
        """macOS: neither enumerator exists, and suggesting ScenePlay-Music
        there would promise a source no browser will list."""
        import shutil
        import routes.obs as ro
        monkeypatch.setattr(shutil, 'which', lambda cmd: None)
        assert ro.music_capture_choices(refresh=True) == []
        assert pactl['calls'] == 0


class TestLabelSelect:
    """The label box is a select now — this machine lists its own devices on
    either OS, so nobody transcribes 'CABLE Output (...)' or remembers
    'ScenePlay-Music'. Same autosave trap as the output select: the saved
    value must be among the options or opening the page erases it."""

    def test_linux_lands_on_the_default_untouched(self, app, settings,
                                                  monkeypatch):
        import routes.obs as ro
        monkeypatch.setattr(ro, 'music_capture_choices',
                            lambda refresh=False: [ro.DEFAULT_MUSIC_LABEL,
                                                   'Built-in Audio'])
        opts = ro.music_label_options()
        assert opts[0] == (ro.DEFAULT_MUSIC_LABEL, ro.DEFAULT_MUSIC_LABEL)
        assert ro.music_device_label() == ro.DEFAULT_MUSIC_LABEL, \
            'nothing saved must mean the app-built source is preselected'

    def test_saved_label_survives_a_failed_probe(self, app, settings,
                                                 monkeypatch):
        """The page autosaves; a vanished option would post the first entry
        back and quietly re-aim the push tab."""
        import routes.obs as ro
        settings['obs_music_device_label'] = 'CABLE Output'
        monkeypatch.setattr(ro, 'music_capture_choices',
                            lambda refresh=False: [])
        assert ro.music_label_options() == [
            ('CABLE Output', 'CABLE Output — saved, not detected right now')]

    def test_detected_saved_label_is_not_listed_twice(self, app, settings,
                                                      monkeypatch):
        import routes.obs as ro
        settings['obs_music_device_label'] = 'CABLE Output'
        monkeypatch.setattr(ro, 'music_capture_choices',
                            lambda refresh=False: ['CABLE Output'])
        vals = [v for v, _ in ro.music_label_options()]
        assert vals.count('CABLE Output') == 1


class TestPlayerRouting:
    def test_windows_mpv_plays_into_the_chosen_cable(self, monkeypatch):
        import relay_audio_stream as ras
        monkeypatch.setattr(ras, '_IS_WIN', True)
        monkeypatch.setattr('sql.appsettingGet',
                            lambda n, d=None: CABLE if n == ras.WIN_DEVICE_SETTING else d)
        assert ras.output_device() == CABLE

    def test_unset_means_the_default_output(self, monkeypatch):
        """Not every table sends music to OBS; those must keep playing out of
        the speakers with no configuration at all."""
        import relay_audio_stream as ras
        monkeypatch.setattr(ras, '_IS_WIN', True)
        monkeypatch.setattr('sql.appsettingGet', lambda n, d=None: '')
        assert ras.output_device() is None

    def test_unreadable_settings_never_stop_playback(self, monkeypatch):
        import relay_audio_stream as ras
        monkeypatch.setattr(ras, '_IS_WIN', True)

        def boom(name, default=None):
            raise RuntimeError('database is locked')
        monkeypatch.setattr('sql.appsettingGet', boom)
        assert ras.output_device() is None

    def test_linux_still_answers_with_the_capture_sink(self, monkeypatch):
        import relay_audio_stream as ras
        monkeypatch.setattr(ras, '_IS_WIN', False)
        monkeypatch.setattr(ras, '_graph_ready', True)
        assert ras.output_device() == ras.SINK_NAME

    def test_mpv_is_launched_with_the_device(self, monkeypatch):
        """The whole point: the setting has to reach the command line. os.name
        is forced because this must hold when the suite runs on Linux too."""
        import subprocess
        import player
        seen = {}

        class _P:
            pid = 4321

            def poll(self):
                return 0

        monkeypatch.setattr(player.os, 'name', 'nt')
        monkeypatch.setattr(player.time, 'sleep', lambda *_a: None)
        monkeypatch.setattr(player, 'appsettingAudioPlayFlagUpdatePID',
                            lambda pid: None)
        monkeypatch.setattr(player._relay_audio, 'output_device',
                            lambda: CABLE, raising=False)

        def fake_popen(args, **kw):
            seen['args'] = args
            return _P()
        monkeypatch.setattr(subprocess, 'Popen', fake_popen)

        player.play_mp3_local('song.mp3', 70, [0, 0, 0, 0])
        assert '--audio-device=' + CABLE in seen['args']

    def test_no_device_no_flag(self, monkeypatch):
        """An empty --audio-device= would be an mpv error, not a default."""
        import subprocess
        import player
        seen = {}

        class _P:
            pid = 4321

            def poll(self):
                return 0

        monkeypatch.setattr(player.os, 'name', 'nt')
        monkeypatch.setattr(player.time, 'sleep', lambda *_a: None)
        monkeypatch.setattr(player, 'appsettingAudioPlayFlagUpdatePID',
                            lambda pid: None)
        monkeypatch.setattr(player._relay_audio, 'output_device',
                            lambda: None, raising=False)
        monkeypatch.setattr(subprocess, 'Popen',
                            lambda args, **kw: (seen.__setitem__('args', args)
                                                or _P()))
        player.play_mp3_local('song.mp3', 70, [0, 0, 0, 0])
        assert not any(str(a).startswith('--audio-device')
                       for a in seen['args'])


class TestRigWarnings:
    """The reason this cost a session to find: nothing on either machine looks
    wrong. OBS shows a live source, the page shows a correct device label, and
    the music plays perfectly out of the GM's speakers."""

    @pytest.fixture(autouse=True)
    def _windows_feed(self, monkeypatch, settings):
        import routes.obs as ro
        monkeypatch.setattr(ro, 'music_cable_platform', lambda: True)
        monkeypatch.setattr(ro, 'music_transport', lambda: 'feed')
        monkeypatch.setattr(ro, '_active_party', lambda: [])
        monkeypatch.setattr(ro, 'obs_is_local', lambda: False)
        monkeypatch.setattr(ro, 'lan_base', lambda: 'http://192.168.4.29:8086')
        settings['obs_card_base'] = 'http://192.168.4.29:8086'

    def test_unrouted_music_is_reported(self, app, settings):
        import routes.obs as ro
        problems = ' '.join(ro.rig_summary()['problems'])
        assert 'virtual cable' in problems
        assert 'Listen to this device' in problems, \
            'routing the music away from the speakers must not be a surprise'

    def test_the_linux_default_label_is_reported(self, app, settings):
        """'ScenePlay-Music' is a PulseAudio remap source. On Windows the
        browser matches nothing and publishes silence."""
        import routes.obs as ro
        settings['music_output_device'] = CABLE
        problems = ' '.join(ro.rig_summary()['problems'])
        assert ro.DEFAULT_MUSIC_LABEL in problems
        assert 'CABLE Output' in problems

    def test_a_wired_cable_is_quiet(self, app, settings):
        import routes.obs as ro
        settings['music_output_device'] = CABLE
        settings['obs_music_device_label'] = 'CABLE Output'
        problems = ' '.join(ro.rig_summary()['problems'])
        assert 'cable' not in problems.lower()

    def test_linux_is_never_asked_for_a_cable(self, app, settings, monkeypatch):
        """It has a sink, and mpv is already pointed at it."""
        import routes.obs as ro
        monkeypatch.setattr(ro, 'music_cable_platform', lambda: False)
        problems = ' '.join(ro.rig_summary()['problems'])
        assert 'cable' not in problems.lower()
