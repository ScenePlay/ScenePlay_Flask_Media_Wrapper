"""Enable Relay asks which session to engage: keep the join code the players
already have ('reuse'), mint a new one ('new'), or — legacy plain enable —
leave the relay session alone ('')."""
import os

import pytest
from flask import Blueprint, Flask
from flask_login import FlaskLoginClient, LoginManager

from extensions import db

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture()
def relay_app(monkeypatch):
    import sys, types
    from models.user import tblUsers
    import routes.relay_admin as ra
    calls = []
    settings = {'relay_enabled': '0', 'relay_session_id': 'sid-old', 'relay_session_code': 'ABC123'}
    monkeypatch.setattr(ra, 'appsettingGet', lambda k, d='': settings.get(k, d))
    monkeypatch.setattr(ra, 'appsettingSet', lambda k, v: settings.__setitem__(k, v))
    monkeypatch.setattr(ra, '_start_session', lambda requested_id=None, requested_code=None:
                        (calls.append(('start', requested_id, requested_code)) or ('NEWCODE' if not requested_code else requested_code, requested_id or 'sid-new')))
    monkeypatch.setattr(ra, '_start_receiver', lambda: calls.append(('receiver',)))
    for name, attrs in (('relay_guard', {'arm': lambda: None, 'disarm_after_grace': lambda: None}),
                        ('relay_ws', {'start': lambda app: None, 'restart': lambda: None}),
                        ('relay_broadcaster', {k: (lambda k=k: calls.append(('push', k))) for k in
                                               ('push_all_characters', 'push_session_users', 'push_character_feeds', 'push_library')})):
        m = types.ModuleType(name); [setattr(m, k, v) for k, v in attrs.items()]
        monkeypatch.setitem(sys.modules, name, m)

    a = Flask(__name__, root_path=REPO)
    a.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    a.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    a.secret_key = 't'
    db.init_app(a)
    login = LoginManager(); login.init_app(a)
    a.register_blueprint(ra.relay_admin_bp)
    stub = Blueprint('auth', __name__)
    stub.add_url_rule('/login', 'login', lambda: ('login', 200))
    a.register_blueprint(stub)
    a.test_client_class = FlaskLoginClient
    with a.app_context():
        db.create_all()

        @login.user_loader
        def _load(uid):
            return db.session.get(tblUsers, int(uid))
        dm = tblUsers(username='gm', display_name='GM', password_hash='x', role='dm',
                      active=1, created_at='2026-01-01 00:00:00')
        db.session.add(dm); db.session.commit()
        yield a, dm, settings, calls
        db.session.remove(); db.drop_all()


def _enable(relay_app, mode):
    a, dm, settings, calls = relay_app
    r = a.test_client(user=dm).post('/ttrpg/relay/toggle', data={'session_mode': mode})
    assert r.status_code == 302 and settings['relay_enabled'] == '1'
    return calls


def test_reuse_keeps_existing_identity(relay_app):
    calls = _enable(relay_app, 'reuse')
    assert ('start', 'sid-old', 'ABC123') in calls
    assert not [c for c in calls if c[0] == 'push']     # _start_session pushed already


def test_new_mints_fresh_code(relay_app):
    calls = _enable(relay_app, 'new')
    assert ('start', None, None) in calls


def test_reuse_without_previous_code_falls_back_to_new(relay_app):
    a, dm, settings, calls = relay_app
    settings['relay_session_code'] = ''
    _enable(relay_app, 'reuse')
    assert ('start', None, None) in calls


def test_plain_enable_leaves_session_alone(relay_app):
    calls = _enable(relay_app, '')
    assert not [c for c in calls if c[0] == 'start']
    assert ('push', 'push_all_characters') in calls


def test_status_page_carries_the_prompt(relay_app):
    a, dm, settings, calls = relay_app
    src = open(os.path.join(REPO, 'templates', 'ttrpg', 'relay_status.html'), encoding='utf-8').read()
    a.jinja_env.parse(src)                              # template compiles
    assert 'spPickOption(' in src and 'name="session_mode"' in src
    assert 'window.prompt' not in src                   # Eric's rule: dropdown, never a typed number
