"""Cron schedule wizard — command building and time/day mapping.

Uses app.test_request_context for request.host; only DB-free actions are
exercised (scene lookup would hit the live database).
"""

import os

import pytest

from app import app
import routes.cronSchedule_table as cw


@pytest.fixture
def ctx():
    with app.test_request_context('http://localhost:8086/api/cronwizard'):
        yield


class TestSchedule:
    def test_every_day(self):
        minute, hour, dow, label = cw._wizard_schedule({'time': '17:55', 'days': [0, 1, 2, 3, 4, 5, 6]})
        assert (minute, hour, dow) == ('55', '17', '*')
        assert label == 'every day at 5:55 PM'

    def test_weekdays_weekends_custom(self):
        assert cw._wizard_schedule({'time': '08:00', 'days': [1, 2, 3, 4, 5]})[2:] == ('1-5', 'on weekdays at 8:00 AM')
        assert cw._wizard_schedule({'time': '12:00', 'days': [0, 6]})[2:] == ('0,6', 'on weekends at 12:00 PM')
        dow, label = cw._wizard_schedule({'time': '00:30', 'days': [1, 3]})[2:]
        assert dow == '1,3' and label == 'on Monday, Wednesday at 12:30 AM'

    def test_invalid_inputs(self):
        with pytest.raises(ValueError):
            cw._wizard_schedule({'time': '25:00', 'days': [1]})
        with pytest.raises(ValueError):
            cw._wizard_schedule({'time': '10:00', 'days': []})
        with pytest.raises(ValueError):
            cw._wizard_schedule({'time': '', 'days': [1]})


class TestCommands:
    def test_allstop_uses_localhost_and_port(self, ctx):
        cmd, label = cw._wizard_command('allstop', {})
        assert 'http://localhost:8086/killqueue' in cmd
        assert 'activatescenes/?id=-1' in cmd
        assert label == 'stop all music and video'

    def test_volume_bounds(self, ctx, monkeypatch):
        # These assert the Linux command strings — force the posix branch
        # so the test passes on any host OS.
        monkeypatch.setattr(os, 'name', 'posix')
        cmd, label = cw._wizard_command('volume', {'volume': 50})
        assert '"volume": 50' in cmd and 'set_volume' in cmd
        with pytest.raises(ValueError):
            cw._wizard_command('volume', {'volume': 101})
        with pytest.raises(ValueError):
            cw._wizard_command('volume', {'volume': -1})

    def test_repeat_and_reboot_and_update(self, ctx, monkeypatch):
        monkeypatch.setattr(os, 'name', 'posix')   # Linux command strings
        assert 'keepmusicplaying/on' in cw._wizard_command('repeat_on', {})[0]
        assert 'keepmusicplaying/off' in cw._wizard_command('repeat_off', {})[0]
        assert cw._wizard_command('reboot', {})[0] == '/usr/bin/sudo /sbin/reboot'
        upd = cw._wizard_command('update', {})[0]
        assert 'git stash' in upd and 'git pull' in upd and 'reboot' in upd

    def test_unknown_action(self, ctx):
        with pytest.raises(ValueError):
            cw._wizard_command('mystery', {})
