"""Dungeon Crawler Carl level collapse: the DM's countdown + note live in the
session's DCC settings and reach every map viewer — the local map's state
poll, the OBS map source, and (via broadcast_game) the portal."""
import json

import pytest
from flask import Blueprint, Flask
from flask_login import FlaskLoginClient, LoginManager

from extensions import db


@pytest.fixture()
def bm_app(monkeypatch):
    from models.user import tblUsers
    from models.ttrpg import tblSessions, tblBattleMaps
    import routes.battlemap as bm_mod
    a = Flask(__name__)
    a.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    a.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    a.secret_key = 't'
    db.init_app(a)
    login = LoginManager(); login.init_app(a)
    a.register_blueprint(bm_mod.battlemap_bp)
    stub = Blueprint('auth', __name__)
    stub.add_url_rule('/login', 'login', lambda: ('login', 200))
    a.register_blueprint(stub)
    a.test_client_class = FlaskLoginClient
    monkeypatch.setattr(bm_mod, '_push_map_state', lambda bm: None)
    with a.app_context():
        db.create_all()

        @login.user_loader
        def _load(uid):
            return db.session.get(tblUsers, int(uid))

        dm = tblUsers(username='gm', display_name='GM', password_hash='x', role='dm',
                      active=1, created_at='2026-01-01 00:00:00')
        db.session.add(dm); db.session.flush()
        sess = tblSessions(title='Crawl', status='active', created_at='2026-01-01 00:00:00',
                           game_system='dcc',
                           system_settings=json.dumps({'floor': 4, 'collapse_at': 1800000000,
                                                       'collapse_note': 'Stairs: NE'}))
        db.session.add(sess); db.session.flush()
        bm = tblBattleMaps(session_id=sess.session_id, name='Floor 4', grid_cols=10, grid_rows=10,
                           created_at='2026-01-01 00:00:00')
        db.session.add(bm); db.session.commit()
        yield a, dm, sess.session_id, bm.map_id
        db.session.remove(); db.drop_all()


def test_map_state_carries_collapse(bm_app):
    a, dm, sid, mid = bm_app
    d = a.test_client(user=dm).get(f'/ttrpg/battlemap/{mid}/state').get_json()
    assert d['collapse'] == {'floor': 4, 'at': 1800000000, 'note': 'Stairs: NE'}


def test_map_state_collapse_is_null_under_5e(bm_app):
    from models.ttrpg import tblSessions
    a, dm, sid, mid = bm_app
    s = db.session.get(tblSessions, sid); s.game_system = 'dnd5e'; s.system_settings = '{}'
    db.session.commit()
    d = a.test_client(user=dm).get(f'/ttrpg/battlemap/{mid}/state').get_json()
    assert d['collapse'] is None
