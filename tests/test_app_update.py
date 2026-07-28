"""One-click updater: output-text classification (returncodes are unreliable
under the SIGCHLD reaper) and the check/run decision flow with subprocess
stubbed out — no network, no real git operations.
"""

import pytest

import app_update


class TestClassifiers:
    def test_git_clean_pull(self):
        assert not app_update.git_failed('Updating 1a2b..3c4d\nFast-forward', '')
        assert not app_update.git_failed('Already up to date.', '')
        # git chats on stderr routinely (e.g. "From github.com:...")
        assert not app_update.git_failed('', 'From https://github.com/x\n   1a2b..3c4d  main -> origin/main')

    def test_git_real_failures(self):
        assert app_update.git_failed('', 'fatal: unable to access repo')
        assert app_update.git_failed('', 'error: Your local changes would be overwritten')
        assert app_update.git_failed('', 'CONFLICT (content): merge conflict in app.py')
        assert app_update.git_failed('', 'timed out after 30s: git fetch')

    def test_pip_warnings_are_not_failures(self):
        assert not app_update.pip_failed(
            'Successfully installed flask-3.0',
            'WARNING: You are using pip version 23; notice: newer available')

    def test_pip_real_failure(self):
        assert app_update.pip_failed(
            '', 'ERROR: Could not find a version that satisfies the requirement nosuchpkg')


class TestCheckUpdates:
    def test_zip_install(self, monkeypatch):
        monkeypatch.setattr(app_update, 'is_git_install', lambda: False)
        d = app_update.check_updates()
        assert d == {'git': False, 'behind': 0, 'commits': [], 'current': '', 'error': ''}

    def test_behind_with_commits(self, monkeypatch):
        monkeypatch.setattr(app_update, 'is_git_install', lambda: True)
        outputs = {
            ('git', 'fetch', '--quiet'): ('', ''),
            ('git', 'log', '-1', '--format=%h %s'): ('abc1234 current thing', ''),
            ('git', 'rev-list', '--count', 'HEAD..@{u}'): ('2', ''),
            ('git', 'log', '--format=%s', 'HEAD..@{u}'): ('Fix maps\nAdd dice', ''),
        }
        monkeypatch.setattr(app_update, '_run',
                            lambda cmd, timeout=180: outputs[tuple(cmd)])
        d = app_update.check_updates()
        assert d['behind'] == 2 and d['commits'] == ['Fix maps', 'Add dice']
        assert d['current'] == 'abc1234 current thing' and not d['error']

    def test_fetch_failure_reported(self, monkeypatch):
        monkeypatch.setattr(app_update, 'is_git_install', lambda: True)
        monkeypatch.setattr(app_update, '_run',
                            lambda cmd, timeout=180: ('', 'fatal: could not resolve host'))
        d = app_update.check_updates()
        assert d['git'] and d['error'] and d['behind'] == 0


class TestRunUpdate:
    def _patch(self, monkeypatch, pull=('Updating 1..2\nFast-forward', ''),
               pip=('Successfully installed', '')):
        import types, sys as _sys
        monkeypatch.setattr(app_update, 'is_git_install', lambda: True)
        monkeypatch.setitem(_sys.modules, 'backup_restore',
                            types.SimpleNamespace(create_backup=lambda label: '/x/sceneplay-pre.zip'))
        calls = []

        def fake_run(cmd, timeout=180):
            calls.append(cmd)
            if cmd[:2] == ['git', 'stash']:
                return 'No local changes to save', ''
            if cmd[:2] == ['git', 'pull']:
                return pull
            if 'pip' in cmd:
                return pip
            return '', ''
        monkeypatch.setattr(app_update, '_run', fake_run)
        return calls

    def test_happy_path(self, monkeypatch):
        calls = self._patch(monkeypatch)
        r = app_update.run_update()
        assert r['ok'] is True
        assert any(c[:2] == ['git', 'pull'] for c in calls)
        assert any('pip' in c for c in calls)

    def test_pull_failure_stops_before_pip(self, monkeypatch):
        calls = self._patch(monkeypatch, pull=('', 'fatal: not possible to fast-forward'))
        r = app_update.run_update()
        assert r['ok'] is False
        assert not any('pip' in c for c in calls)   # never reached

    def test_pip_failure_blocks_restart_flag(self, monkeypatch):
        self._patch(monkeypatch, pip=('', 'ERROR: No matching distribution'))
        r = app_update.run_update()
        assert r['ok'] is False

    def test_backup_failure_stops_everything(self, monkeypatch):
        import types, sys as _sys

        def boom(label):
            raise RuntimeError('disk full')
        monkeypatch.setattr(app_update, 'is_git_install', lambda: True)
        monkeypatch.setitem(_sys.modules, 'backup_restore',
                            types.SimpleNamespace(create_backup=boom))
        calls = []
        monkeypatch.setattr(app_update, '_run',
                            lambda cmd, timeout=180: calls.append(cmd) or ('', ''))
        r = app_update.run_update()
        assert r['ok'] is False and calls == []     # no git ops at all


class TestAuthDetection:
    """'Not signed in to the code server' must produce the friendly login
    alert, not raw git-speak or a 30s hang-then-timeout."""

    @pytest.mark.parametrize('err', [
        "fatal: could not read Username for 'https://github.com': "
        "terminal prompts disabled",
        "fatal: could not read Password for 'https://x@github.com': "
        "No such device or address",
        "remote: Support for password authentication was removed on "
        "August 13, 2021.\nfatal: Authentication failed for 'https://...'",
        "git@github.com: Permission denied (publickey).\n"
        "fatal: Could not read from remote repository.",
        "Host key verification failed.\nfatal: Could not read from remote",
    ])
    def test_auth_failures_recognized(self, err):
        assert app_update.git_auth_needed('', err)
        assert app_update.git_failed('', err)      # still a failure overall

    def test_non_auth_failures_not_flagged(self):
        assert not app_update.git_auth_needed('', 'fatal: could not resolve host')
        assert not app_update.git_auth_needed('Already up to date.', '')

    def test_check_updates_gives_login_alert(self, monkeypatch):
        monkeypatch.setattr(app_update, 'is_git_install', lambda: True)
        monkeypatch.setattr(
            app_update, '_run',
            lambda cmd, timeout=180: ('', "fatal: could not read Username for "
                                          "'https://github.com': terminal prompts disabled"))
        d = app_update.check_updates()
        assert d['error'] == app_update.GIT_LOGIN_HELP

    def test_run_update_gives_login_alert_on_pull(self, monkeypatch):
        monkeypatch.setattr(app_update, 'is_git_install', lambda: True)

        class FakeBackup:
            @staticmethod
            def create_backup(label=''):
                return '/tmp/x.zip'
        import sys as _sys
        monkeypatch.setitem(_sys.modules, 'backup_restore', FakeBackup)

        def fake_run(cmd, timeout=180, input_text=None):
            if cmd[:2] == ['git', 'stash']:
                return ('No local changes to save', '')
            if cmd[:2] == ['git', 'pull']:
                return ('', 'git@github.com: Permission denied (publickey).\n'
                            'fatal: Could not read from remote repository.')
            return ('', '')
        monkeypatch.setattr(app_update, '_run', fake_run)
        d = app_update.run_update()
        assert d['ok'] is False
        assert app_update.GIT_LOGIN_HELP in d['log']
