"""Secret hygiene: the Gemini API key (and everything under instance/) must
never be able to reach git. Layered defense with the local pre-commit hook
(scripts/git-hooks/pre-commit); these tests are the tracked, always-running
half — they fail the suite the moment an ignore rule regresses or a
key-shaped string lands in a tracked file."""
import os
import subprocess

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

pytestmark = pytest.mark.skipif(
    not os.path.isdir(os.path.join(REPO, '.git')),
    reason='not a git checkout (deployment tree)')


def _git(*args):
    return subprocess.run(['git', *args], cwd=REPO,
                          capture_output=True, text=True)


class TestSecretHygiene:
    # NOTE: all assertions classify by git's OUTPUT, never its returncode —
    # app.py's SIGCHLD reaper (installed once any test imports app) steals
    # child exit statuses, making returncodes read 0 regardless (the same
    # reality app_update.py documents).

    def test_instance_secrets_are_gitignored(self):
        r = _git('check-ignore', 'instance/gemini_api_key',
                 'instance/secret_key')
        ignored = set(r.stdout.split())
        assert {'instance/gemini_api_key', 'instance/secret_key'} <= ignored, \
            f'instance/ must stay in .gitignore (got: {r.stdout!r})'

    def test_nothing_under_instance_is_tracked(self):
        r = _git('ls-files', 'instance/')
        assert r.stdout.strip() == '', \
            f'files under instance/ are tracked: {r.stdout}'

    def test_no_tracked_file_contains_a_key_shaped_string(self):
        # Google API keys are AIza + 35 url-safe chars; sk-... covers other
        # providers. git grep scans TRACKED files only; no output = clean.
        r = _git('grep', '-I', '-l', '-E',
                 'AIza[0-9A-Za-z_-]{35}|sk-[A-Za-z0-9_-]{32,}', '--', '.')
        assert r.stdout.strip() == '', \
            f'tracked files contain key-shaped strings: {r.stdout}'

    def test_gemini_key_path_points_into_instance(self):
        import gemini
        rel = os.path.relpath(gemini._KEY_PATH, REPO)
        assert rel.split(os.sep)[0] == 'instance', rel

    def test_key_never_travels_in_a_url(self):
        # The client must send the key only as a header — a key in a URL ends
        # up in server/proxy logs. Check CODE lines that build/issue requests
        # (the module docstring may mention '?key=' while forbidding it).
        src = open(os.path.join(REPO, 'gemini.py')).read()
        for line in src.splitlines():
            if 'API_BASE' in line or 'requests.' in line:
                assert '?key' not in line and 'key={' not in line, line
        assert 'x-goog-api-key' in src
