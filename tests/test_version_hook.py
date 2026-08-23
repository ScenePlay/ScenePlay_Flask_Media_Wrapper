"""The pre-commit hook's auto-version step: every commit bumps the patch
number in version.py AND pyproject.toml and stages both; a hand-edited,
already-staged version is respected; SP_NO_BUMP=1 skips the bump."""
import os
import shutil
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOK = os.path.join(ROOT, 'scripts', 'git-hooks', 'pre-commit')

pytestmark = pytest.mark.skipif(
    not (shutil.which('git') and shutil.which('bash')),
    reason='needs git and bash (the hook is a bash script)')


def _git(repo, *args, env=None):
    e = dict(os.environ, GIT_AUTHOR_NAME='t', GIT_AUTHOR_EMAIL='t@x', GIT_COMMITTER_NAME='t',
             GIT_COMMITTER_EMAIL='t@x', **(env or {}))
    return subprocess.run(['git', *args], cwd=repo, env=e, capture_output=True, text=True, check=True)


def _write(repo, version):
    with open(os.path.join(repo, 'version.py'), 'w') as f:
        f.write(f'"""doc"""\n\n__version__ = "{version}"\n')
    with open(os.path.join(repo, 'pyproject.toml'), 'w') as f:
        f.write(f'[project]\nname = "sceneplay"\nversion = "{version}"\n')


def _read(repo):
    with open(os.path.join(repo, 'version.py')) as f:
        v = [l for l in f if l.startswith('__version__')][0].split('"')[1]
    with open(os.path.join(repo, 'pyproject.toml')) as f:
        p = [l for l in f if l.startswith('version')][0].split('"')[1]
    return v, p


@pytest.fixture
def repo(tmp_path):
    r = str(tmp_path / 'repo')
    os.makedirs(r)
    _git(r, 'init', '-q')
    _git(r, 'config', 'commit.gpgsign', 'false')
    shutil.copy(HOOK, os.path.join(r, '.git', 'hooks', 'pre-commit'))
    os.chmod(os.path.join(r, '.git', 'hooks', 'pre-commit'), 0o755)
    _write(r, '1.3.0')
    _git(r, 'add', '.')
    _git(r, 'commit', '-q', '-m', 'seed', env={'SP_NO_BUMP': '1'})
    assert _read(r) == ('1.3.0', '1.3.0')
    return r


def _committed_version(repo):
    src = _git(repo, 'show', 'HEAD:version.py').stdout
    return [l for l in src.splitlines() if l.startswith('__version__')][0].split('"')[1]


class TestAutoBump:
    def test_every_commit_bumps_patch_in_both_files(self, repo):
        with open(os.path.join(repo, 'notes.txt'), 'w') as f:
            f.write('x')
        _git(repo, 'add', 'notes.txt')
        out = _git(repo, 'commit', '-q', '-m', 'change').stdout + _git(repo, 'log', '-1', '--stat').stdout
        assert _read(repo) == ('1.3.1', '1.3.1')
        assert _committed_version(repo) == '1.3.1'            # staged INTO the same commit
        assert 'pyproject.toml' in out and 'version.py' in out
        with open(os.path.join(repo, 'notes.txt'), 'a') as f:
            f.write('y')
        _git(repo, 'commit', '-q', '-am', 'again')
        assert _read(repo) == ('1.3.2', '1.3.2')
        assert _git(repo, 'status', '--porcelain').stdout == ''   # nothing left dirty

    def test_hand_edited_version_is_respected(self, repo):
        _write(repo, '2.0.0')
        _git(repo, 'add', 'version.py', 'pyproject.toml')
        _git(repo, 'commit', '-q', '-m', 'major')
        assert _read(repo) == ('2.0.0', '2.0.0')
        assert _committed_version(repo) == '2.0.0'

    def test_sp_no_bump_skips(self, repo):
        with open(os.path.join(repo, 'notes.txt'), 'w') as f:
            f.write('x')
        _git(repo, 'add', 'notes.txt')
        _git(repo, 'commit', '-q', '-m', 'no bump', env={'SP_NO_BUMP': '1'})
        assert _read(repo) == ('1.3.0', '1.3.0')

    def test_secret_guard_still_blocks(self, repo):
        with open(os.path.join(repo, 'leak.txt'), 'w') as f:
            f.write('key = "AIza' + 'A' * 35 + '"\n')
        _git(repo, 'add', 'leak.txt')
        head = _git(repo, 'rev-parse', 'HEAD').stdout.strip()
        # Judge by effect, not return code: once any test has imported app.py
        # the process-wide SIGCHLD reaper makes subprocess exit codes lie.
        e = dict(os.environ, GIT_AUTHOR_NAME='t', GIT_AUTHOR_EMAIL='t@x',
                 GIT_COMMITTER_NAME='t', GIT_COMMITTER_EMAIL='t@x')
        r = subprocess.run(['git', 'commit', '-q', '-m', 'oops'], cwd=repo, env=e,
                           capture_output=True, text=True)
        assert 'COMMIT BLOCKED' in r.stderr
        assert _git(repo, 'rev-parse', 'HEAD').stdout.strip() == head   # no commit happened
        assert _read(repo) == ('1.3.0', '1.3.0')               # blocked before the bump
