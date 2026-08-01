"""Clearing the shared roll feed (battlemap top bar > Clear Rolls).

The delete is the easy half. The half worth pinning down is the watermark: the
relay receiver re-imports rolls it has seen, so without it the feed refills by
itself seconds after the DM clears it.
"""
import pytest

from extensions import db
from models.tblRollLog import tblRollLog
from models.ttrpg import tblDiceRolls
from routes.ttrpg import clear_roll_history


@pytest.fixture
def settings(monkeypatch):
    """appsettingSet writes to the real database file, not the test one."""
    import sql
    store = {}
    monkeypatch.setattr(sql, 'appsettingSet',
                        lambda k, v: store.__setitem__(k, v))
    return store


@pytest.fixture
def rolls(app):
    for i in range(3):
        db.session.add(tblDiceRolls(
            char_name='Alice', expression='1d20', label='', dice_json='[7]',
            modifier=0, total=7, adv_mode='normal',
            rolled_at=f'2026-01-0{i + 1} 12:00:00'))
    db.session.commit()
    return app


class TestClearRollHistory:
    def test_empties_the_feed(self, rolls, settings):
        assert tblDiceRolls.query.count() == 3
        clear_roll_history()
        assert tblDiceRolls.query.count() == 0

    def test_reports_how_many_went(self, rolls, settings):
        assert clear_roll_history() == 3

    def test_sets_the_relay_watermark(self, rolls, settings):
        """Without this the receiver re-imports what was just cleared."""
        clear_roll_history()
        assert 'relay_roll_cleared_at' in settings
        assert settings['relay_roll_cleared_at']

    def test_clears_the_session_roll_log_too(self, app, settings):
        from models.user import tblUsers
        from models.ttrpg import tblSessions
        user = tblUsers(username='dm', display_name='DM', password_hash='x',
                        role='dm', active=1, created_at='2026-01-01 00:00:00')
        db.session.add(user)
        db.session.flush()
        sess = tblSessions(title='S1', status='active',
                           created_at='2026-01-01 00:00:00')
        db.session.add(sess)
        db.session.flush()
        db.session.add(tblRollLog(session_id=sess.session_id, player_name='Bob',
                                  roll_expr='1d20', result=12, breakdown='',
                                  rolled_at='2026-01-01 12:00:00'))
        db.session.commit()
        assert tblRollLog.query.count() == 1
        clear_roll_history()
        assert tblRollLog.query.count() == 0

    def test_clearing_an_empty_feed_is_harmless(self, app, settings):
        assert clear_roll_history() == 0
        assert tblDiceRolls.query.count() == 0

    def test_new_rolls_after_a_clear_still_land(self, rolls, settings):
        """The watermark must not bar rolls made AFTER the clear."""
        clear_roll_history()
        db.session.add(tblDiceRolls(
            char_name='Cara', expression='1d6', label='', dice_json='[4]',
            modifier=0, total=4, adv_mode='normal',
            rolled_at='2026-02-01 12:00:00'))
        db.session.commit()
        assert tblDiceRolls.query.count() == 1
