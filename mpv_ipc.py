"""IPC to the two mpv instances, addressed by socket name (music / video).

Linux: /tmp/mpvsocket-<kind> via socat, one input command per line.
Windows: the same socket is a named pipe, written directly.
Either way a dead socket fails SILENTLY — same contract as the transport
controls have always had against an idle player.

Lives in its own module so both the transport routes (routes/main.py) and
the kill helpers (sql.py) can share it without an import cycle.
"""
import os
import time


def mpv_command(kind, command):
    if os.name == 'nt':
        try:
            with open(f'\\\\.\\pipe\\mpvsocket-{kind}', 'r+b', buffering=0) as pipe:
                pipe.write(command.encode() + b'\n')
        except OSError:
            pass   # player not running — no-op, like socat against a dead socket
    else:
        os.system(f"echo {command} | socat - /tmp/mpvsocket-{kind}")


# 12 steps of `add volume -10` reach silence from ANY starting volume (mpv
# clamps at 0), so the current volume never has to be read back off the
# socket.
_FADE_STEPS = 12
_FADE_SECONDS = 1.2


def music_fade_out():
    """Taper the music player to silence right before a kill, so skips and
    scene switches don't cut a song off mid-waveform. The relay stream
    captures mpv's sink output, so remote players hear the same taper.

    No restore afterwards: the process dies immediately, and the next track
    spawns with its own --volume plus an afade fade-in (mpvAudio.sh /
    player.py), which rises back up to the user's setting.

    Gated on a live player — against a dead socket the commands are no-ops
    and the fade would only burn its sleep time."""
    try:
        from sql import appsettingAudioPlayPID
        from procutil import pid_alive
        if not pid_alive(int(appsettingAudioPlayPID()[0][2])):
            return
    except Exception:
        return
    for _ in range(_FADE_STEPS):
        mpv_command('music', 'add volume -10')
        time.sleep(_FADE_SECONDS / _FADE_STEPS)
