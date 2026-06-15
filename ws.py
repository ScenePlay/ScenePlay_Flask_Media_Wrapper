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
    app.startTheadPlayer()
    serve(app.app, host='0.0.0.0', port=8086, threads=8)
