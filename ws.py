from waitress import serve
import app

# app.py is imported here (not run as __main__), so its own __main__ guard never
# starts the music/video/yt-dlp worker processes. We start them ourselves below.
#
# The guard is REQUIRED: on Python 3.14 the default multiprocessing start method
# on Linux is 'forkserver', which re-imports THIS module in every worker child.
# Without the guard, each spawned worker would re-run startTheadPlayer() and
# serve() (port clash + a spawn loop). Under 'forkserver'/'spawn' the child sees
# __name__ == '__mp_main__', so this block runs only in the real entry process.
if __name__ == '__main__':
    # Refuse to run beside another instance: startTheadPlayer() would spawn a
    # SECOND set of queue workers polling the same DB (they race for rows, and
    # a half-dead instance silently steals + fails downloads). Port 8086 being
    # taken means an instance is already up — bail before starting anything.
    import os, socket, sys
    _probe = socket.socket()
    # Linux: without SO_REUSEADDR a fresh restart false-positives on the old
    # socket's TIME_WAIT. Windows must NOT set it (it lets bind hijack a LIVE
    # listener, defeating the check); its bind ignores TIME_WAIT anyway.
    if os.name != 'nt':
        _probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        _probe.bind(('0.0.0.0', 8086))
    except OSError:
        print('*** ScenePlay is already running (port 8086 in use) — '
              'not starting a second instance. ***')
        sys.exit(1)
    finally:
        _probe.close()

    # Loud (non-fatal) dependency check: mpv is the player on both OSes and
    # yt-dlp needs ffmpeg on PATH for its extract/merge steps — a box missing
    # either boots fine but silently fails at playback/download time.
    import shutil
    for _tool, _why in (('mpv', 'music/video playback'),
                        ('ffmpeg', 'yt-dlp audio extract / video merge')):
        if not shutil.which(_tool):
            print(f'*** WARNING: {_tool!r} not found on PATH — {_why} will fail. ***')

    app.startTheadPlayer()
    serve(app.app, host='0.0.0.0', port=8086, threads=8)
