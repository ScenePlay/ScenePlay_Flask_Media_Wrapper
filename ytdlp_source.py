"""Run yt-dlp from a git checkout, refreshed before every download.

Python port of youtube.sh's clone-once / pull-every-run behavior (lines
32-37 there), shared by both OSes: YouTube changes constantly and a frozen
yt-dlp starts failing, so the Linux model always pulled master first. The
checkout lives at <repo root>/yt-dlp (gitignored), exactly where youtube.sh
put it. When git or the network is unavailable the pip-installed yt_dlp is
the fallback, so downloads degrade instead of breaking.
"""
import os
import subprocess

_BASE = os.path.dirname(os.path.realpath(__file__))
REPO_DIR = os.path.join(_BASE, 'yt-dlp')
_REPO_URL = 'https://github.com/yt-dlp/yt-dlp.git'
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
_GIT_TIMEOUT = 180


def _checkout_usable():
    # yt_dlp package dir present == runnable source tree
    return os.path.isdir(os.path.join(REPO_DIR, 'yt_dlp'))


def refresh():
    """Clone once, pull otherwise. Returns True when a usable checkout exists.

    Mirrors youtube.sh: a failed PULL is a warning (keep the existing copy);
    a failed CLONE means no checkout, and popen_env() falls back to pip.
    --depth 1 keeps the first clone small; pulls stay shallow.
    """
    try:
        if os.path.isdir(os.path.join(REPO_DIR, '.git')):
            r = subprocess.run(['git', '-C', REPO_DIR, 'pull', '--ff-only'],
                               capture_output=True, text=True,
                               timeout=_GIT_TIMEOUT, creationflags=_NO_WINDOW)
            if r.returncode != 0:
                print('ytdlp_source: warning: could not update yt-dlp, '
                      'using existing copy: ' + (r.stderr or '').strip())
        else:
            r = subprocess.run(['git', 'clone', '--depth', '1', _REPO_URL, REPO_DIR],
                               capture_output=True, text=True,
                               timeout=_GIT_TIMEOUT, creationflags=_NO_WINDOW)
            if r.returncode != 0:
                print('ytdlp_source: warning: could not clone yt-dlp, '
                      'falling back to the pip-installed copy: '
                      + (r.stderr or '').strip())
    except Exception as e:
        print(f'ytdlp_source: warning: git refresh failed ({e}); '
              'using existing/pip copy')
    return _checkout_usable()


def popen_env():
    """Environment for `python -m yt_dlp` runs: the checkout is prepended to
    PYTHONPATH so the git code wins over the pip install. Plain environment
    when no checkout exists (pip fallback)."""
    env = os.environ.copy()
    if _checkout_usable():
        prev = env.get('PYTHONPATH')
        env['PYTHONPATH'] = REPO_DIR + (os.pathsep + prev if prev else '')
    return env
