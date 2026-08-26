"""Data-driven chimes (chimes.py): registry-rendered config, per-event
switch + sound, legacy dl_sound_* fallback, missing-file fallback, and the
never-raise path resolution the download worker relies on."""
import pytest

import chimes


@pytest.fixture
def env(tmp_path):
    d = tmp_path / 'effects'; d.mkdir()
    for n in ('finished.mp3', 'failed.mp3', 'gong.wav', '.hidden.mp3', 'notes.txt'):
        (d / n).write_bytes(b'x')
    store = {}
    get = lambda n, default=None: store.get(n, default)   # noqa: E731
    set_ = lambda n, v: store.__setitem__(n, str(v))      # noqa: E731
    return str(d), store, get, set_


class TestRegistry:
    def test_sounds_listed_defaults_first(self, env):
        d, *_ = env
        assert chimes.available_sounds(d) == ['failed.mp3', 'finished.mp3', 'gong.wav']

    def test_config_defaults(self, env):
        d, store, get, _ = env
        cfg = {c['key']: c for c in chimes.config(get, d)}
        assert set(cfg) == {'download_ok', 'download_fail'}
        assert cfg['download_ok']['enabled'] and cfg['download_ok']['file'] == 'finished.mp3'

    def test_legacy_switch_honoured_until_new_key_set(self, env):
        d, store, get, set_ = env
        store['dl_sound_ok'] = '0'
        assert chimes.chime_path(get, d, 'download_ok') is None
        chimes.save(get, set_, d, 'download_ok', enabled=True)
        assert chimes.chime_path(get, d, 'download_ok').endswith('finished.mp3')
        assert store['dl_sound_ok'] == '1', 'legacy key kept in step'


class TestSaveAndResolve:
    def test_pick_sound_and_switch_off(self, env):
        d, store, get, set_ = env
        assert chimes.save(get, set_, d, 'download_fail', file='gong.wav')
        assert chimes.chime_path(get, d, 'download_fail').endswith('gong.wav')
        assert chimes.save(get, set_, d, 'download_fail', enabled=False)
        assert chimes.chime_path(get, d, 'download_fail') is None

    def test_unknown_sound_or_event_refused(self, env):
        d, store, get, set_ = env
        assert not chimes.save(get, set_, d, 'download_ok', file='notes.txt')
        assert not chimes.save(get, set_, d, 'download_ok', file='../etc.mp3')
        assert not chimes.save(get, set_, d, 'level_up', enabled=True)
        assert chimes.chime_path(get, d, 'level_up') is None

    def test_missing_chosen_file_falls_back_to_default(self, env):
        d, store, get, set_ = env
        store['chime_download_ok_file'] = 'gone.mp3'
        assert chimes.chime_path(get, d, 'download_ok').endswith('finished.mp3')
        cfg = {c['key']: c for c in chimes.config(get, d)}
        assert cfg['download_ok']['missing'] and cfg['download_ok']['file'] == 'finished.mp3'

    def test_settings_failure_means_default_sound_not_silence(self, env):
        d, *_ = env
        def boom(n, default=None): raise RuntimeError('no table')
        assert chimes.chime_path(boom, d, 'download_ok').endswith('finished.mp3')

    def test_safe_names(self):
        assert chimes.safe_sound_name('My Chime-1.mp3') and chimes.safe_sound_name('x.WAV')
        assert not chimes.safe_sound_name('../x.mp3') and not chimes.safe_sound_name('x.exe') and not chimes.safe_sound_name('.x.mp3')
