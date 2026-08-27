"""The dice roller follows the ACTIVE session's game system.

/ttrpg/dice/roll stamps the outcome into the roll label (so the feed and the
relay carry meaning with no schema change), /ttrpg/dice/system tells open
rollers which rules apply, and the session edit endpoint stores the DM's
choice (+ Floor) and re-broadcasts it while the session is live."""
import json

import pytest
from flask import Blueprint, Flask
from flask_login import FlaskLoginClient, LoginManager

from extensions import db


@pytest.fixture()
def dice_app(monkeypatch):
    from models.user import tblUsers
    from models.ttrpg import tblSessions
    import relay_broadcaster
    import routes.ttrpg as ttrpg_mod

    pushed = []
    monkeypatch.setattr(relay_broadcaster, 'broadcast_roll', lambda *a, **k: None)
    monkeypatch.setattr(relay_broadcaster, 'broadcast_game', lambda sess: pushed.append(sess.game_info()))

    a = Flask(__name__)
    a.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    a.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    a.secret_key = 't'
    db.init_app(a)
    login = LoginManager()
    login.init_app(a)
    a.register_blueprint(ttrpg_mod.ttrpg)
    stub = Blueprint('auth', __name__)
    stub.add_url_rule('/login', 'login', lambda: ('login', 200))
    a.register_blueprint(stub)
    a.test_client_class = FlaskLoginClient

    with a.app_context():
        db.create_all()

        @login.user_loader
        def _load(uid):
            return db.session.get(tblUsers, int(uid))

        dm = tblUsers(username='gm', display_name='GM', password_hash='x',
                      role='dm', active=1, created_at='2026-01-01 00:00:00')
        db.session.add(dm)
        db.session.flush()
        sess = tblSessions(title='Crawl', status='active', created_at='2026-01-01 00:00:00',
                           game_system='dcc', system_settings='{"floor": 3}')
        db.session.add(sess)
        db.session.commit()
        yield a, dm, sess.session_id, pushed
        db.session.remove()
        db.drop_all()


def _roll(client, **body):
    base = {'character_id': None, 'char_name': 'Carl', 'count': 1, 'sides': 20,
            'modifier': 4, 'label': 'Attack', 'adv_mode': 'normal'}
    base.update(body)
    return client.post('/ttrpg/dice/roll', json=base).get_json()


class TestDiceSystemEndpoint:
    def test_reports_active_session_system(self, dice_app):
        a, dm, sid, _ = dice_app
        d = a.test_client(user=dm).get('/ttrpg/dice/system').get_json()
        assert d == {'id': 'dcc', 'name': 'Dungeon Crawler Carl',
                     'settings': {'floor': 3, 'collapse_at': 0, 'collapse_note': ''}}

    def test_default_when_no_active_session(self, dice_app):
        from models.ttrpg import tblSessions
        a, dm, sid, _ = dice_app
        db.session.get(tblSessions, sid).status = 'ended'
        db.session.commit()
        d = a.test_client(user=dm).get('/ttrpg/dice/system').get_json()
        assert d['id'] == 'dnd5e' and d['settings'] == {}


class TestRollOutcome:
    def test_outcome_stamped_into_label(self, dice_app, monkeypatch):
        import random
        monkeypatch.setattr(random, 'randint', lambda a, b: 15)
        a, dm, sid, _ = dice_app
        d = _roll(a.test_client(user=dm), roll_type='attack', difficulty=17)
        assert d['total'] == 19
        assert d['outcome']['degree'] == 'success'
        assert d['label'] == 'Attack vs 17 → Hit'
        assert d['system'] == 'dcc' and d['difficulty'] == 17
        # the stored row (what the feed and relay carry) has the same label
        from models.ttrpg import tblDiceRolls
        assert tblDiceRolls.query.one().label == 'Attack vs 17 → Hit'

    def test_floor_defaults_from_session(self, dice_app, monkeypatch):
        import random
        monkeypatch.setattr(random, 'randint', lambda a, b: 15)
        a, dm, sid, _ = dice_app
        d = _roll(a.test_client(user=dm), roll_type='attack', difficulty=9)   # +10 → amazing
        assert d['outcome']['degree'] == 'amazing'
        assert '+3 bonus damage' in d['label']

    def test_disadvantage_judges_kept_die(self, dice_app, monkeypatch):
        import random
        seq = iter([20, 2])
        monkeypatch.setattr(random, 'randint', lambda a, b: next(seq))
        a, dm, sid, _ = dice_app
        d = _roll(a.test_client(user=dm), roll_type='check', difficulty=16, adv_mode='disadvantage')
        assert d['total'] == 6 and d['outcome']['degree'] == 'major_fail'

    def test_rankup(self, dice_app, monkeypatch):
        import random
        monkeypatch.setattr(random, 'randint', lambda a, b: 9)
        a, dm, sid, _ = dice_app
        d = _roll(a.test_client(user=dm), roll_type='rankup', rank=8, modifier=0, label='Rank-Up')
        assert d['label'] == 'Rank-Up → Rank up! Skill goes to Rank 9'

    def test_plain_roll_untouched(self, dice_app, monkeypatch):
        import random
        monkeypatch.setattr(random, 'randint', lambda a, b: 4)
        a, dm, sid, _ = dice_app
        d = _roll(a.test_client(user=dm), sides=6, count=2, modifier=0, label='Damage')
        assert d['label'] == 'Damage' and d['outcome']['text'] == ''

    def test_5e_session_uses_5e_rules(self, dice_app, monkeypatch):
        import random
        from models.ttrpg import tblSessions
        monkeypatch.setattr(random, 'randint', lambda a, b: 15)
        a, dm, sid, _ = dice_app
        s = db.session.get(tblSessions, sid)
        s.game_system = 'dnd5e'; s.system_settings = '{}'
        db.session.commit()
        d = _roll(a.test_client(user=dm), roll_type='attack', difficulty=17)
        assert d['label'] == 'Attack vs 17 → Success' and d['system'] == 'dnd5e'


class TestSessionEdit:
    def test_stores_choice_and_broadcasts_while_active(self, dice_app):
        from models.ttrpg import tblSessions
        a, dm, sid, pushed = dice_app
        r = a.test_client(user=dm).post(f'/ttrpg/sessions/{sid}/edit',
                                        json={'game_system': 'dcc', 'floor': 7})
        d = r.get_json()
        assert d['ok'] and d['game'] == {'id': 'dcc', 'name': 'Dungeon Crawler Carl',
                                         'settings': {'floor': 7, 'collapse_at': 0, 'collapse_note': ''}}
        assert json.loads(db.session.get(tblSessions, sid).system_settings)['floor'] == 7
        assert pushed and pushed[-1]['settings']['floor'] == 7

    def test_level_collapse_edits_keep_floor_and_broadcast(self, dice_app):
        """The map page's live widget sends only the collapse fields; the Floor
        and everything else must survive, and the portal gets the change."""
        from models.ttrpg import tblSessions
        a, dm, sid, pushed = dice_app
        c = a.test_client(user=dm)
        c.post(f'/ttrpg/sessions/{sid}/edit', json={'floor': 5})
        d = c.post(f'/ttrpg/sessions/{sid}/edit',
                   json={'collapse_at': 1800000000, 'collapse_note': 'Stairs: NE tower'}).get_json()
        assert d['game']['settings'] == {'floor': 5, 'collapse_at': 1800000000, 'collapse_note': 'Stairs: NE tower'}
        assert pushed[-1]['settings']['collapse_at'] == 1800000000
        # clearing the countdown keeps the note; junk is coerced, notes are capped
        d = c.post(f'/ttrpg/sessions/{sid}/edit', json={'collapse_at': 0}).get_json()
        assert d['game']['settings']['collapse_at'] == 0 and d['game']['settings']['collapse_note'] == 'Stairs: NE tower'
        d = c.post(f'/ttrpg/sessions/{sid}/edit', json={'collapse_at': 'soon', 'collapse_note': 'x' * 500}).get_json()
        assert d['game']['settings']['collapse_at'] == 0 and len(d['game']['settings']['collapse_note']) == 200
        assert json.loads(db.session.get(tblSessions, sid).system_settings)['floor'] == 5
        # 5e sessions carry no collapse keys at all
        d = c.post(f'/ttrpg/sessions/{sid}/edit', json={'game_system': 'dnd5e'}).get_json()
        assert d['game']['settings'] == {}

    def test_unknown_system_falls_back(self, dice_app):
        a, dm, sid, pushed = dice_app
        d = a.test_client(user=dm).post(f'/ttrpg/sessions/{sid}/edit',
                                        json={'game_system': 'gurps'}).get_json()
        assert d['game']['id'] == 'dnd5e' and d['game']['settings'] == {}

    def test_planning_session_does_not_broadcast(self, dice_app):
        from models.ttrpg import tblSessions
        a, dm, sid, pushed = dice_app
        db.session.get(tblSessions, sid).status = 'planning'
        db.session.commit()
        a.test_client(user=dm).post(f'/ttrpg/sessions/{sid}/edit', json={'floor': 9})
        assert pushed == []


class TestSheetFollowsItsOwnSystem:
    def test_5e_character_in_dcc_session_rolls_5e(self, dice_app, monkeypatch):
        """A character sheet rolls under the CHARACTER's rules even when the live
        session runs the other game (the map/monster rollers follow the session)."""
        import random
        from models.ttrpg import tblCharacters
        monkeypatch.setattr(random, 'randint', lambda a, b: 15)
        a, dm, sid, _ = dice_app
        bob = tblCharacters(user_id=dm.user_id, name='Bob', level=3, hp_current=20, hp_max=30, created_at='t')
        db.session.add(bob); db.session.commit()
        d = _roll(a.test_client(user=dm), character_id=bob.character_id, roll_type='attack', difficulty=17)
        assert d['system'] == 'dnd5e' and d['label'] == 'Attack vs 17 → Success'
        d = _roll(a.test_client(user=dm), roll_type='attack', difficulty=17)          # no character: session rules
        assert d['system'] == 'dcc' and d['label'] == 'Attack vs 17 → Hit'
