"""LAN discovery of OBS boxes (discovery.py).

Unit level: the socket sweep and the obs-websocket Hello are stubbed, so what
these pin down is the identify/record logic — that an OBS responder is labelled,
that a box running BOTH ScenePlay and OBS keeps its ScenePlay role, and that the
merge never writes two rows or clobbers a hand-typed name."""
import pytest

import discovery
from extensions import db
from models.serverIP import tblserversip as ServerIP
from models.serverRole import tblserverrole as ServerRole


def _seed_roles():
    for name, order in (('None', 10), ('Main', 20), ('WLED', 40)):
        db.session.add(ServerRole(name=name, active=1, orderBy=order))
    db.session.commit()


def _role(name):
    r = ServerRole.query.filter(ServerRole.name == name).first()
    return r.ID if r else None


class TestIdentifyObs:
    def test_hello_frame_is_accepted_and_versioned(self, monkeypatch):
        class FakeWS:
            def recv(self):
                return ('{"op":0,"d":{"obsWebSocketVersion":"5.5.2",'
                        '"rpcVersion":1}}')
            def close(self):
                pass

        import websocket
        monkeypatch.setattr(websocket, 'create_connection',
                            lambda *a, **k: FakeWS())
        dev = discovery._identify_obs('10.0.0.5')
        assert dev == {'kind': 'obs', 'ip': '10.0.0.5', 'name': 'OBS Studio',
                       'version': '5.5.2', 'locked': False}

    def test_password_protected_obs_is_still_found(self, monkeypatch):
        class FakeWS:
            def recv(self):
                return ('{"op":0,"d":{"obsWebSocketVersion":"5.5.2",'
                        '"authentication":{"challenge":"x","salt":"y"}}}')
            def close(self):
                pass

        import websocket
        monkeypatch.setattr(websocket, 'create_connection',
                            lambda *a, **k: FakeWS())
        dev = discovery._identify_obs('10.0.0.5')
        assert dev['kind'] == 'obs' and dev['locked'] is True

    def test_a_non_obs_socket_is_dropped(self, monkeypatch):
        class FakeWS:
            def recv(self):
                return 'HTTP/1.1 400 Bad Request'   # not JSON
            def close(self):
                pass

        import websocket
        monkeypatch.setattr(websocket, 'create_connection',
                            lambda *a, **k: FakeWS())
        assert discovery._identify_obs('10.0.0.9') is None

    def test_a_refused_connection_is_dropped(self, monkeypatch):
        import websocket

        def boom(*a, **k):
            raise OSError('connection refused')

        monkeypatch.setattr(websocket, 'create_connection', boom)
        assert discovery._identify_obs('10.0.0.9') is None


class TestRecordObs:
    def test_obs_only_box_is_named_and_roled(self, app):
        _seed_roles()
        devices = [{'kind': 'obs', 'ip': '10.0.0.5', 'name': 'OBS Studio',
                    'version': '5.5.2', 'locked': False}]
        created, updated = discovery._record(devices, {'10.0.0.5': {4455}})
        assert (created, updated) == (1, 0)
        row = ServerIP.query.filter(ServerIP.ipAddress == '10.0.0.5').first()
        assert row.serverName == 'OBS Studio'
        assert row.version == '5.5.2'
        assert row.ports == '4455'
        assert row.serverroleid == _role('OBS'), 'OBS role auto-created & set'

    def test_obs_role_is_backfilled_when_missing(self, app):
        # Only the base roles exist — no 'OBS'. Recording must create it.
        _seed_roles()
        assert _role('OBS') is None
        discovery._record(
            [{'kind': 'obs', 'ip': '10.0.0.5', 'name': 'OBS Studio',
              'version': '5.5.2'}], {'10.0.0.5': {4455}})
        assert _role('OBS') is not None

    def test_sceneplay_plus_obs_is_one_row_keeping_the_sceneplay_identity(
            self, app):
        _seed_roles()
        devices = [
            {'kind': 'sceneplay', 'ip': '10.0.0.7', 'name': 'Table Rig',
             'version': '2.1', 'is_led': False},
            {'kind': 'obs', 'ip': '10.0.0.7', 'name': 'OBS Studio',
             'version': '5.5.2', 'locked': False},
        ]
        created, updated = discovery._record(
            devices, {'10.0.0.7': {8086, 4455}})
        rows = ServerIP.query.filter(ServerIP.ipAddress == '10.0.0.7').all()
        assert len(rows) == 1, 'the two responders merge into one row'
        row = rows[0]
        assert row.serverName == 'Table Rig'       # ScenePlay name wins
        assert row.version == '2.1'
        assert row.ports == '4455, 8086'           # both ports listed
        # A ScenePlay box is not forced onto the OBS role; 4455 in ports is the
        # signal it runs OBS. Left on the placeholder here (no manual choice).
        assert row.serverroleid == _role('None')

    def test_a_manual_role_survives_a_rescan(self, app):
        _seed_roles()
        row = ServerIP(ipAddress='10.0.0.5', serverName='My OBS',
                       serverroleid=_role('Main'))
        db.session.add(row)
        db.session.commit()
        discovery._record(
            [{'kind': 'obs', 'ip': '10.0.0.5', 'name': 'OBS Studio',
              'version': '5.5.2'}], {'10.0.0.5': {4455}})
        row = ServerIP.query.filter(ServerIP.ipAddress == '10.0.0.5').first()
        assert row.serverroleid == _role('Main'), 'manual role stands'
        assert row.serverName == 'My OBS', 'hand-typed name is not clobbered'


class TestSweepPorts:
    def test_obs_port_is_in_the_default_sweep(self):
        import inspect
        default = inspect.signature(discovery.sweep).parameters['ports'].default
        assert discovery.OBS_PORT in default


class TestScannedObsPickList:
    """The Broadcast page's server picker (routes.obs._scanned_obs_servers):
    every scanned row with 4455 in its ports column, named, sorted."""

    def test_only_4455_rows_are_offered(self, app):
        from routes.obs import _scanned_obs_servers
        db.session.add_all([
            ServerIP(ipAddress='10.0.0.5', serverName='Rig',
                     ports='4455, 8086'),
            ServerIP(ipAddress='10.0.0.6', serverName='Table',
                     ports='8086'),
            ServerIP(ipAddress='10.0.0.7', serverName='Lights', ports='80'),
        ])
        db.session.commit()
        assert _scanned_obs_servers() == [{'ip': '10.0.0.5', 'name': 'Rig'}]

    def test_a_nameless_row_falls_back_to_its_ip(self, app):
        from routes.obs import _scanned_obs_servers
        db.session.add(ServerIP(ipAddress='10.0.0.5', serverName='  ',
                                ports='4455'))
        db.session.commit()
        assert _scanned_obs_servers() == [{'ip': '10.0.0.5',
                                           'name': '10.0.0.5'}]

    def test_sorted_by_name_and_4455_is_matched_exactly(self, app):
        from routes.obs import _scanned_obs_servers
        db.session.add_all([
            ServerIP(ipAddress='10.0.0.9', serverName='zeta', ports='4455'),
            ServerIP(ipAddress='10.0.0.8', serverName='Alpha', ports='4455'),
            # '14455' must NOT count as 4455
            ServerIP(ipAddress='10.0.0.4', serverName='Odd', ports='14455'),
        ])
        db.session.commit()
        assert [s['name'] for s in _scanned_obs_servers()] == ['Alpha', 'zeta']
