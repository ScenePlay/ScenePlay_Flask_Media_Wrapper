"""One-click software update: git pull + pip install + app restart.

Driven from the Utilities page (DM-only). Flow:
  check_updates()  git fetch, compare HEAD to upstream -> {behind, commits}
  run_update()     safety backup -> git stash -> git pull --ff-only ->
                   pip install -r requirements.txt -> (Linux) nginx upload fix
  restart_app()    exit this process; the Linux watchdog relaunches it with
                   the new code, on Windows a detached helper re-runs
                   startApp.bat. restarting.html covers the wait in the UI.

IMPORTANT: the app installs a process-wide SIGCHLD reaper (app.py) that
steals child exit statuses, so subprocess return codes are unreliable on
Linux. Success/failure here is judged on OUTPUT TEXT, never returncode.

ZIP installs (no .git directory) can't self-update — check_updates reports
that and the UI explains the re-download path instead.
"""

import os
import subprocess
import sys
import threading

REPO_ROOT = os.path.dirname(os.path.realpath(__file__))


def is_git_install():
    return os.path.isdir(os.path.join(REPO_ROOT, '.git'))


def _run(cmd, timeout=180, input_text=None):
    """Run a command in the repo root; return (stdout, stderr) text.
    Never raises on failure — callers classify by output. input_text is
    fed to stdin (used to hand sudo -S its password).

    git is forced NON-INTERACTIVE: a remote that wants a login must FAIL with
    a readable message instead of prompting. Without this, git prompts for a
    username/password on the server's terminal (or a tty that isn't there)
    and the web request just hangs until the timeout — the useless
    'timed out after 30s: git fetch' failure mode."""
    env = None
    if cmd and cmd[0] == 'git':
        env = dict(os.environ,
                   GIT_TERMINAL_PROMPT='0',
                   GIT_SSH_COMMAND='ssh -oBatchMode=yes')
    try:
        p = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True,
                           text=True, timeout=timeout, input=input_text,
                           env=env)
        return (p.stdout or '').strip(), (p.stderr or '').strip()
    except subprocess.TimeoutExpired:
        return '', f'timed out after {timeout}s: {" ".join(cmd)}'
    except Exception as e:
        return '', f'failed to run {" ".join(cmd)}: {e}'


def _sudo_blocked(out, err):
    """True when sudo could not run because of a missing/wrong password.
    Both -n (fail instead of prompting) and -S (password from stdin) name
    the reason on stderr."""
    low = (err or '').lower()
    return any(m in low for m in ('password is required',
                                  'authentication is required',
                                  'a terminal is required',
                                  'no askpass program',
                                  'incorrect password',
                                  'no password was provided',
                                  'sorry, try again'))


def git_failed(out, err):
    """True when git output names a real failure (returncodes lie here)."""
    low = (err or '').lower()
    return any(m in low for m in ('fatal:', 'error:', 'conflict',
                                  'permission denied', 'not a git repository',
                                  'could not resolve', 'timed out', 'failed to run'))


def git_auth_needed(out, err):
    """True when git failed because this machine isn't logged in to the code
    server (missing/rejected credentials, no SSH key) — the messages git
    emits when GIT_TERMINAL_PROMPT=0 / BatchMode stop it from prompting."""
    low = ((out or '') + '\n' + (err or '')).lower()
    return any(m in low for m in (
        'could not read username',
        'could not read password',
        'terminal prompts disabled',
        'authentication failed',
        'invalid username or password',
        'permission denied (publickey',
        'host key verification failed',
        'support for password authentication was removed',
    ))


GIT_LOGIN_HELP = (
    'Update server login required — this computer is not signed in to the '
    'code server, so it cannot download the new version. Open a terminal in '
    'the ScenePlay folder and run "git pull" once to sign in (or set up an '
    'SSH key / credential helper), then run the update again.'
)


def pip_failed(out, err):
    """True when pip output names a real failure. pip prints WARNINGs and
    notices to stderr routinely — only ERROR lines mean the install failed."""
    combined = (out or '') + '\n' + (err or '')
    low = combined.lower()
    return ('error:' in low or 'timed out' in low.split('\n')[0]
            or 'failed to run' in low.split('\n')[0])


def check_updates():
    """Fetch and report how far behind upstream we are. Read-only and safe.
    Returns {git, behind, commits, current, error}."""
    if not is_git_install():
        return {'git': False, 'behind': 0, 'commits': [],
                'current': '', 'error': ''}
    out, err = _run(['git', 'fetch', '--quiet'], timeout=30)
    if git_failed(out, err):
        if git_auth_needed(out, err):
            return {'git': True, 'behind': 0, 'commits': [], 'current': '',
                    'error': GIT_LOGIN_HELP}
        return {'git': True, 'behind': 0, 'commits': [], 'current': '',
                'error': f'Could not check for updates: {err or out}'}
    current, _ = _run(['git', 'log', '-1', '--format=%h %s'])
    count, err2 = _run(['git', 'rev-list', '--count', 'HEAD..@{u}'])
    if git_failed(count, err2) or not count.isdigit():
        return {'git': True, 'behind': 0, 'commits': [], 'current': current,
                'error': f'Could not compare with the update server: {err2 or count}'}
    commits, _ = _run(['git', 'log', '--format=%s', 'HEAD..@{u}'])
    return {'git': True, 'behind': int(count),
            'commits': [c for c in commits.split('\n') if c][:20],
            'current': current, 'error': ''}


def run_update(sudo_password=None):
    """Execute the update. Returns {ok, log} — log is a list of step lines.
    Stops at the first real failure and never restarts into a broken state.
    sudo_password (optional, from the web page) unlocks the sudo step; it is
    passed to sudo -S on stdin and never logged."""
    log = []

    def step(title, text=''):
        log.append(f'== {title}')
        if text:
            log.append(text)

    if not is_git_install():
        return {'ok': False, 'log': ['This copy was installed from a ZIP '
                                     '(no .git folder) — download the new ZIP '
                                     'and re-run the installer instead.']}

    # 1. safety backup (existing light-archive system: DB + uploaded images)
    try:
        import backup_restore
        path = backup_restore.create_backup(label='pre-update')
        step('Safety backup created', os.path.basename(path))
    except Exception as e:
        step('Safety backup FAILED', str(e))
        log.append('Stopping — refusing to update without a safety backup.')
        return {'ok': False, 'log': log}

    # 2. stash local edits to tracked files (keeps tinkered configs safe;
    #    untracked files — ScenePlay.db, instance/, media — are never touched)
    out, err = _run(['git', 'stash'])
    step('Protecting local changes (git stash)', out or err)
    if git_failed(out, err):
        return {'ok': False, 'log': log}

    # 3. pull, fast-forward only: a diverged history should stop with a clear
    #    message, never auto-merge on a game box
    out, err = _run(['git', 'pull', '--ff-only'], timeout=300)
    step('Downloading update (git pull)', out or err)
    if git_failed(out, err):
        if git_auth_needed(out, err):
            log.append(GIT_LOGIN_HELP)
        else:
            log.append('Update aborted — the app was NOT changed. '
                       '(If this says "diverging", the local copy has been '
                       'modified; resolve it in a terminal.)')
        return {'ok': False, 'log': log}

    # 4. Python packages — sys.executable IS the venv python
    out, err = _run([sys.executable, '-m', 'pip', 'install', '-r',
                     'requirements.txt'], timeout=600)
    step('Installing Python packages (pip)', (out + '\n' + err).strip()[-2000:])
    if pip_failed(out, err):
        log.append('Package install failed — NOT restarting. The previous '
                   'code is still running; fix the error above and retry.')
        return {'ok': False, 'log': log}

    if os.name != 'nt':
        # 5. idempotent nginx upload-size fix (covers pull-only boxes that
        #    predate it); best-effort — nginx may legitimately be absent.
        # sudo must NEVER prompt on the server's terminal (that leaves the
        # web request hanging on an invisible password prompt): -S reads the
        # password the web page supplied from stdin, -n fails fast instead
        # of prompting when no password was given.
        script = os.path.join(REPO_ROOT, 'supportFiles',
                              'fixNginxUploadSize.sh')
        if sudo_password:
            out, err = _run(['sudo', '-S', '-p', '', 'bash', script],
                            timeout=60, input_text=sudo_password + '\n')
        else:
            out, err = _run(['sudo', '-n', 'bash', script], timeout=60)
        if _sudo_blocked(out, err):
            step('nginx upload-size fix SKIPPED — sudo needs your system '
                 'password' + (' (the one entered was not accepted)'
                               if sudo_password else '') + '.',
                 'The update itself is unaffected. To apply this fix, enter '
                 'your system password in the update box and run the update '
                 'again, or run in a terminal: '
                 'sudo bash supportFiles/fixNginxUploadSize.sh')
        else:
            step('nginx upload-size fix (best-effort)', out or err)
        # 6. new shell scripts must stay executable
        _run(['bash', '-c', 'chmod +x *.sh supportFiles/*.sh 2>/dev/null'])

    log.append('Update complete — restarting ScenePlay…')
    return {'ok': True, 'log': log}


def restart_app(delay=3.0):
    """Exit this process after `delay` seconds. Linux: the watchdog service
    relaunches it (≤ ~30 s). Windows: a detached helper console re-runs
    startApp.bat after the port frees up."""
    def _die():
        if os.name == 'nt':
            bat = os.path.join(REPO_ROOT, 'startApp.bat')
            DETACHED = 0x00000008 | 0x00000200   # DETACHED | NEW_PROCESS_GROUP
            try:
                subprocess.Popen(
                    ['cmd', '/c', f'timeout /t 6 /nobreak >nul & start "" "{bat}"'],
                    cwd=REPO_ROOT, creationflags=DETACHED)
            except Exception:
                pass
        os._exit(0)
    threading.Timer(delay, _die).start()
