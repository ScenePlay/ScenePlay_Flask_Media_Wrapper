"""Recording and streaming control.

Stopping either one is irreversible in the moment — the take ends, or the
broadcast drops for everyone watching — so the API is explicit about the state
it wants rather than toggling. A toggle acts on what the caller last heard,
which turns a double-click or a stale poll into an accidental go-live.
"""
import os

import pytest
from flask import Flask
from flask_login import FlaskLoginClient, LoginManager

from extensions import db

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture()
def dm_client(monkeypatch):
    """A logged-in DM hitting the real blueprint.

    The shared `app` fixture registers no blueprints and has no login manager,
    and these routes are behind @login_required + @dm_required — so build the
    smallest app that exercises them for real rather than calling the view
    functions directly and skipping the guards entirely.
    """
    from models.user import tblUsers
    from routes.obs import obs_bp

    a = Flask(__name__, template_folder=os.path.join(REPO, 'templates'),
              static_folder=os.path.join(REPO, 'static'))
    a.config.update(SQLALCHEMY_DATABASE_URI='sqlite://',
                    SQLALCHEMY_TRACK_MODIFICATIONS=False,
                    SECRET_KEY='test', TESTING=True)
    db.init_app(a)
    login = LoginManager()
    login.init_app(a)
    a.register_blueprint(obs_bp)
    a.test_client_class = FlaskLoginClient

    with a.app_context():
        db.create_all()

        @login.user_loader
        def _load(uid):
            return db.session.get(tblUsers, int(uid))

        dm = tblUsers(username='gm', display_name='GM', password_hash='x',
                      role='dm', active=1, created_at='2026-01-01 00:00:00')
        db.session.add(dm)
        db.session.commit()
        with a.test_client(user=dm) as c:
            yield c
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def obs(monkeypatch):
    """Recording stub of the obs_ws surface these routes use."""
    import obs_ws
    calls = []
    state = {'stream': False, 'record': False, 'connected': True}

    def set_output_active(kind, on, timeout=5):
        calls.append((kind, on))
        state[kind] = on
        return on

    monkeypatch.setattr(obs_ws, 'connected', lambda: state['connected'])
    monkeypatch.setattr(obs_ws, 'set_output_active', set_output_active)
    monkeypatch.setattr(obs_ws, '_record_error', lambda *a, **k: None)
    return {'calls': calls, 'state': state}


class TestSetOutputActive:
    """The obs_ws helper, against a stub of the socket."""

    @pytest.fixture()
    def ws(self, monkeypatch):
        import obs_ws
        sent = []
        active = {'v': False}

        def fake_request(rtype, data=None, timeout=3):
            sent.append(rtype)
            if rtype == 'StartStream':
                active['v'] = True
            elif rtype == 'StopStream':
                active['v'] = False
            elif rtype == 'GetStreamStatus':
                return {'outputActive': active['v']}
            elif rtype == 'GetRecordStatus':
                return {'outputActive': active['v']}
            return {}
        monkeypatch.setattr(obs_ws, 'request', fake_request)
        return sent

    def test_start_reads_the_state_back(self, ws):
        """Never assume: the cache is event-fed and the event may not have
        landed, and a button that lies about being live is worse than none."""
        import obs_ws
        assert obs_ws.set_output_active('stream', True) is True
        assert ws == ['StartStream', 'GetStreamStatus']

    def test_waits_for_a_slow_output_to_come_up(self, monkeypatch):
        """Measured against real OBS: the status read straight after
        StartRecord still says inactive. One read would paint "Start
        recording" while recording."""
        import obs_ws
        reads = {'n': 0}

        def fake_request(rtype, data=None, timeout=3):
            if rtype == 'GetRecordStatus':
                reads['n'] += 1
                return {'outputActive': reads['n'] >= 3}   # lags by two reads
            return {}
        monkeypatch.setattr(obs_ws, 'request', fake_request)
        assert obs_ws.set_output_active('record', True) is True
        assert reads['n'] >= 3, 'gave up before the output came up'

    def test_gives_up_and_reports_the_truth(self, monkeypatch):
        """An output that never comes up — a bad stream key — must report NOT
        active rather than hanging or claiming success."""
        import obs_ws

        def fake_request(rtype, data=None, timeout=3):
            return {'outputActive': False}
        monkeypatch.setattr(obs_ws, 'request', fake_request)
        assert obs_ws.set_output_active('stream', True, settle=0.3) is False

    def test_stop_issues_the_stop_request(self, ws):
        import obs_ws
        obs_ws.set_output_active('stream', True)
        ws.clear()
        assert obs_ws.set_output_active('stream', False) is False
        assert ws[0] == 'StopStream'

    @pytest.mark.parametrize('code', [500, 501])
    def test_already_in_that_state_is_success(self, monkeypatch, code):
        """OBS rejects starting what is running. The DM still got what they
        asked for, so it must not surface as an error."""
        import obs_ws

        def fake_request(rtype, data=None, timeout=3):
            if rtype in ('StartRecord', 'StopRecord'):
                raise obs_ws.ObsRejected(code, 'output already in that state')
            return {'outputActive': True}
        monkeypatch.setattr(obs_ws, 'request', fake_request)
        assert obs_ws.set_output_active('record', True) is True

    def test_other_rejections_still_raise(self, monkeypatch):
        """A stream that cannot start — bad key, no server — must be reported,
        not silently swallowed as 'already streaming'."""
        import obs_ws

        def fake_request(rtype, data=None, timeout=3):
            raise obs_ws.ObsRejected(600, 'no stream service configured')
        monkeypatch.setattr(obs_ws, 'request', fake_request)
        with pytest.raises(obs_ws.ObsRejected):
            obs_ws.set_output_active('stream', True)


class TestOutputRoute:
    def _post(self, client, kind, on):
        return client.post(f'/ttrpg/obs/api/output/{kind}', json={'on': on})

    def test_unknown_output_is_rejected(self, dm_client, obs):
        r = self._post(dm_client, 'teleport', True)
        assert r.status_code == 400
        assert obs['calls'] == []

    def test_not_connected_is_503(self, dm_client, obs):
        obs['state']['connected'] = False
        r = self._post(dm_client, 'record', True)
        assert r.status_code == 503
        assert obs['calls'] == [], 'must not reach OBS while disconnected'

    def test_start_and_stop_are_explicit(self, dm_client, obs):
        """The route asks for a state, never 'the other one'."""
        assert self._post(dm_client, 'record', True).get_json()['active'] is True
        assert self._post(dm_client, 'record', False).get_json()['active'] is False
        assert obs['calls'] == [('record', True), ('record', False)]

    def test_missing_body_means_stop_not_start(self, dm_client, obs):
        """A malformed request must never be what puts the broadcast live."""
        r = dm_client.post('/ttrpg/obs/api/output/stream')
        assert r.status_code == 200
        assert obs['calls'] == [('stream', False)]

    def test_rejection_becomes_502(self, dm_client, obs, monkeypatch):
        import obs_ws

        def boom(kind, on, timeout=5):
            raise obs_ws.ObsRejected(600, 'no stream service configured')
        monkeypatch.setattr(obs_ws, 'set_output_active', boom)
        r = self._post(dm_client, 'stream', True)
        assert r.status_code == 502
        assert 'no stream service' in r.get_json()['error']

    def test_lost_connection_becomes_503(self, dm_client, obs, monkeypatch):
        import obs_ws

        def boom(kind, on, timeout=5):
            raise obs_ws.ObsUnavailable('socket closed')
        monkeypatch.setattr(obs_ws, 'set_output_active', boom)
        assert self._post(dm_client, 'record', True).status_code == 503


class TestRoomRotation:
    """A new room per broadcast, so last week's link is not a way in."""

    def _post(self, client, kind, on):
        return client.post(f'/ttrpg/obs/api/output/{kind}', json={'on': on})

    def test_starting_a_stream_mints_a_new_room(self, dm_client, obs,
                                                monkeypatch):
        import routes.obs as ro
        store = {'obs_room_per_stream': '1', 'obs_vdo_room': 'oldroom'}
        monkeypatch.setattr(ro, 'appsettingGet',
                            lambda n, d=None: store.get(n, d))
        monkeypatch.setattr(ro, 'appsettingSet', store.__setitem__)
        d = self._post(dm_client, 'stream', True).get_json()
        assert d['new_room'] and d['new_room'] != 'oldroom'
        assert store['obs_vdo_room'] == d['new_room']

    def test_stopping_a_stream_never_rotates(self, dm_client, obs, monkeypatch):
        """Rotating on the way OUT would strand the table for no reason."""
        import routes.obs as ro
        store = {'obs_room_per_stream': '1', 'obs_vdo_room': 'keepme'}
        monkeypatch.setattr(ro, 'appsettingGet',
                            lambda n, d=None: store.get(n, d))
        monkeypatch.setattr(ro, 'appsettingSet', store.__setitem__)
        assert self._post(dm_client, 'stream', False).get_json()['new_room'] == ''
        assert store['obs_vdo_room'] == 'keepme'

    def test_recording_never_rotates(self, dm_client, obs, monkeypatch):
        """Only the public broadcast justifies stranding everyone."""
        import routes.obs as ro
        store = {'obs_room_per_stream': '1', 'obs_vdo_room': 'keepme'}
        monkeypatch.setattr(ro, 'appsettingGet',
                            lambda n, d=None: store.get(n, d))
        monkeypatch.setattr(ro, 'appsettingSet', store.__setitem__)
        assert self._post(dm_client, 'record', True).get_json()['new_room'] == ''
        assert store['obs_vdo_room'] == 'keepme'

    def test_off_by_default_leaves_the_room_alone(self, dm_client, obs,
                                                  monkeypatch):
        import routes.obs as ro
        store = {'obs_vdo_room': 'keepme'}
        monkeypatch.setattr(ro, 'appsettingGet',
                            lambda n, d=None: store.get(n, d))
        monkeypatch.setattr(ro, 'appsettingSet', store.__setitem__)
        assert self._post(dm_client, 'stream', True).get_json()['new_room'] == ''
        assert store['obs_vdo_room'] == 'keepme'
