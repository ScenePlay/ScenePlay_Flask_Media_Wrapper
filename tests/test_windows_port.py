"""Windows-port seams: per-OS mpv launch/transport, download job contract,
schtasks day mapping, per-OS wizard commands.

All tests run on Linux — Windows behavior is exercised by monkeypatching
os.name, and subprocesses are faked.
"""

import os
import sys

import pytest


# ── yt_que.YT_Exec — the shared download pipeline ──────────────────────────────

class _FakePopen:
    def __init__(self, argv, on_spawn=None):
        self.argv = argv
        self.pid = 4242
        if on_spawn:
            on_spawn()

    def poll(self):
        return 0


@pytest.fixture
def yt(monkeypatch, tmp_path):
    import yt_que
    calls = {'argv': None, 'status': None, 'chime': None, 'pid': None}

    monkeypatch.setattr(yt_que, 'appsettingYT_QuePlayFlagUpdatePID',
                        lambda pid: calls.__setitem__('pid', pid))
    monkeypatch.setattr(yt_que, 'CRUD_tblMusic',
                        lambda row, op: calls.__setitem__('status', (row, op)))
    monkeypatch.setattr(yt_que, 'CRUD_tblvideomedia',
                        lambda row, op: calls.__setitem__('status', (row, op)))
    monkeypatch.setattr(yt_que, 'play_mp3',
                        lambda fi: calls.__setitem__('chime', os.path.basename(fi)))
    monkeypatch.setattr(yt_que.time, 'sleep', lambda s: None)
    # never git-clone/pull in tests; popen_env() then returns the plain env
    monkeypatch.setattr(yt_que.ytdlp_source, 'refresh', lambda: False)
    return yt_que, calls, tmp_path


def test_download_success_moves_file_status3_chime(yt, monkeypatch):
    yt_que, calls, tmp_path = yt
    start_dir = os.path.dirname(os.path.abspath(yt_que.__file__))
    name = 'zz_test_dl_ok.mp3'

    def spawn(argv, **kw):
        calls['argv'] = argv
        # yt-dlp "downloaded" the file into the repo root (cwd)
        return _FakePopen(argv, on_spawn=lambda: open(os.path.join(start_dir, name), 'wb').write(b'x'))
    monkeypatch.setattr(yt_que.subprocess, 'Popen', spawn)

    dest_dir = str(tmp_path) + '/'
    fi = [[7, dest_dir, name, 'https://u', 'mp3', 'tblMusic']]
    yt_que.YT_Exec(fi)

    assert calls['argv'][:3] == [sys.executable, '-m', 'yt_dlp']
    assert '-x' in calls['argv'] and f'--output={name}' in calls['argv']
    assert '--no-playlist' in calls['argv']
    assert os.path.exists(dest_dir + name)              # moved into place
    assert not os.path.exists(os.path.join(start_dir, name))
    assert calls['status'] == ([7, 3], 'dnUpdate')      # Finished
    assert calls['chime'] == 'finished.mp3'
    assert calls['pid'] == 4242


def test_download_failure_status4_failed_chime(yt, monkeypatch):
    yt_que, calls, tmp_path = yt
    monkeypatch.setattr(yt_que.subprocess, 'Popen',
                        lambda argv, **kw: calls.__setitem__('argv', argv) or _FakePopen(argv))
    fi = [[9, str(tmp_path) + '/', 'zz_missing.mp4', 'https://u', 'mp4', 'tblVideoMedia']]
    yt_que.YT_Exec(fi)
    assert calls['status'] == ([9, 4], 'dnUpdate')      # Failed
    assert calls['chime'] == 'failed.mp3'
    # video format flags used
    assert '--merge-output-format' in calls['argv'] and 'mp4' in calls['argv']


def test_dash_leading_video_id_is_not_a_flag(yt, monkeypatch):
    yt_que, calls, tmp_path = yt
    monkeypatch.setattr(yt_que.subprocess, 'Popen',
                        lambda argv, **kw: calls.__setitem__('argv', argv) or _FakePopen(argv))
    fi = [[1, str(tmp_path) + '/', '-abc123.mp3', 'https://u', 'mp3', 'tblMusic']]
    yt_que.YT_Exec(fi)
    assert '--output=-abc123.mp3' in calls['argv']      # '=' form survives


# ── mpv launch argv (Windows branch mirrors mpv.sh/mpvAudio.sh flags) ──────────

def test_nt_video_argv_matches_mpv_sh_flags(monkeypatch):
    import mpvPlayer
    argv = {}
    monkeypatch.setattr(os, 'name', 'nt')
    monkeypatch.setattr(mpvPlayer.subprocess, 'Popen',
                        lambda a, **kw: argv.update(a=a) or _FakePopen(a))
    monkeypatch.setattr(mpvPlayer, 'appsettingVideoPlayFlagUpdatePID', lambda p: None)
    monkeypatch.setattr(mpvPlayer.time, 'sleep', lambda s: None)
    mpvPlayer.play_mpv_local('file.mp4', 1, 80, [0] * 10, 2)
    a = argv['a']
    assert a[0] == 'mpv' and a[1] == 'file.mp4'
    for flag in ('--no-terminal', '--fullscreen=yes', '--speed=1',
                 '--loop-file=2', '--volume=80', '--screen=1',
                 '--input-ipc-server=\\\\.\\pipe\\mpvsocket-video'):
        assert flag in a, flag


def test_nt_audio_argv_matches_mpvaudio_sh_flags(monkeypatch):
    import player
    argv = {}
    monkeypatch.setattr(os, 'name', 'nt')
    monkeypatch.setattr(player.subprocess, 'Popen',
                        lambda a, **kw: argv.update(a=a) or _FakePopen(a))
    monkeypatch.setattr(player, 'appsettingAudioPlayFlagUpdatePID', lambda p: None)
    monkeypatch.setattr(player.time, 'sleep', lambda s: None)
    player.play_mp3_local('song.mp3', 65, [0] * 10)
    a = argv['a']
    assert a[0] == 'mpv' and a[1] == 'song.mp3'
    for flag in ('--no-terminal', '--no-video', '--force-window=no',
                 '--volume=65',
                 '--input-ipc-server=\\\\.\\pipe\\mpvsocket-music'):
        assert flag in a, flag


def test_linux_launch_paths_unchanged(monkeypatch):
    """Linux must keep spawning the battle-tested shell wrappers."""
    import player, mpvPlayer
    seen = []
    monkeypatch.setattr(os, 'name', 'posix')   # assert the Linux branch on any host OS
    fake = lambda a, **kw: seen.append(a) or _FakePopen(a)
    monkeypatch.setattr(player.subprocess, 'Popen', fake)
    monkeypatch.setattr(mpvPlayer.subprocess, 'Popen', fake)
    monkeypatch.setattr(player, 'appsettingAudioPlayFlagUpdatePID', lambda p: None)
    monkeypatch.setattr(mpvPlayer, 'appsettingVideoPlayFlagUpdatePID', lambda p: None)
    monkeypatch.setattr(player.time, 'sleep', lambda s: None)
    monkeypatch.setattr(mpvPlayer.time, 'sleep', lambda s: None)
    player.play_mp3_local('s.mp3', 50, [0] * 10)
    mpvPlayer.play_mpv_local('v.mp4', 0, 70, [0] * 10, 0)
    assert seen[0][0] == './mpvAudio.sh' and seen[1][0] == './mpv.sh'


# ── schtasks day mapping + per-OS wizard commands ───────────────────────────────

def test_schtasks_day_mapping():
    from routes.cronSchedule_table import _nt_schtasks_days
    assert _nt_schtasks_days('*') == 'SUN,MON,TUE,WED,THU,FRI,SAT'
    assert _nt_schtasks_days('1-5') == 'MON,TUE,WED,THU,FRI'
    assert _nt_schtasks_days('0,6') == 'SUN,SAT'
    assert _nt_schtasks_days('1,3') == 'MON,WED'
    assert _nt_schtasks_days('7') == 'SUN'          # cron allows 7 = Sunday
    assert _nt_schtasks_days('*/2') is None         # inexpressible -> skip
    assert _nt_schtasks_days('mon') is None


def test_wizard_commands_per_os(monkeypatch):
    from app import app
    import routes.cronSchedule_table as cw
    with app.test_request_context('http://localhost:8086/'):
        # Linux strings (unchanged) — force the posix branch on any host OS
        monkeypatch.setattr(os, 'name', 'posix')
        cmd, _ = cw._wizard_command('reboot', {})
        assert cmd == '/usr/bin/sudo /sbin/reboot'
        assert '/usr/bin/curl' in cw._wizard_command('allstop', {})[0]

        monkeypatch.setattr(os, 'name', 'nt')
        assert cw._wizard_command('reboot', {})[0] == 'shutdown /r /t 0'
        allstop = cw._wizard_command('allstop', {})[0]
        assert 'timeout /t 2 /nobreak >NUL' in allstop and allstop.startswith('curl ')
        vol = cw._wizard_command('volume', {'volume': 50})[0]
        assert '-d "{\\"volume\\": 50}"' in vol       # cmd.exe quoting
        upd = cw._wizard_command('update', {})[0]
        assert upd.startswith('cd /d ') and 'shutdown /r /t 0' in upd


# ── yt-dlp module invocation in the metadata/playlist workers ──────────────────

def test_workers_use_pip_ytdlp():
    import meta_que, playlist_que
    assert meta_que._YTDLP_CMD == [sys.executable, '-m', 'yt_dlp']
    assert playlist_que._YTDLP_CMD == [sys.executable, '-m', 'yt_dlp']
