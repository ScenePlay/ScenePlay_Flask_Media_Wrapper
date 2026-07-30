"""obs_ws client internals: the v5 auth digest, request/reply correlation,
error mapping, event-driven cache, backoff. Pure tests — no sockets; the
reader thread is simulated by resolving _pending slots directly."""
import base64
import hashlib
import json
import threading

import pytest

import obs_ws as ow


@pytest.fixture(autouse=True)
def clean_state(monkeypatch):
    monkeypatch.setattr(ow, '_state', 'connected')
    monkeypatch.setattr(ow, '_pending', {})
    monkeypatch.setattr(ow, '_record_error', lambda *a: None)   # no live DB writes
    monkeypatch.setattr(ow, '_clear_error', lambda *a: None)
    with ow._cache_lock:
        ow._cache.update(ow._blank_cache())
    yield


class FakeWs:
    def __init__(self):
        self.sent = []
        self.fail = False

    def send(self, raw):
        if self.fail:
            raise OSError('broken pipe')
        self.sent.append(json.loads(raw))


def _serve_reply(builder, delay=0.01):
    """Background 'reader': answers the next pending request."""
    def run():
        import time
        time.sleep(delay)
        for rid, slot in list(ow._pending.items()):
            slot['reply'] = builder(rid)
            slot['evt'].set()
    t = threading.Thread(target=run, daemon=True)
    t.start()
    return t


def _ok(rid, data=None):
    return {'op': 7, 'd': {'requestId': rid, 'requestStatus': {'result': True, 'code': 100},
                           'responseData': data or {}}}


def _err(rid, code=600, comment='no such scene'):
    return {'op': 7, 'd': {'requestId': rid,
                           'requestStatus': {'result': False, 'code': code,
                                             'comment': comment}}}


class TestAuth:
    def test_digest_matches_spec(self):
        # b64(sha256(b64(sha256(password + salt)) + challenge)) — pinned here
        # because a wrong digest is indistinguishable from a wrong password.
        pw = 'supersecretpassword'
        salt = 'lM1GncleQOaCu9lT1yeUZhFYnqhsLLP1G5lAGo3ixaI='
        challenge = '+IxH4CnCiqpX1rM9scsNynZzbOe4KhDeYcTNS3PDaeY='
        secret = base64.b64encode(
            hashlib.sha256((pw + salt).encode()).digest()).decode()
        expect = base64.b64encode(
            hashlib.sha256((secret + challenge).encode()).digest()).decode()
        assert ow._auth_digest(pw, salt, challenge) == expect

    def test_digest_is_deterministic_and_password_sensitive(self):
        a = ow._auth_digest('pw', 's', 'c')
        assert a == ow._auth_digest('pw', 's', 'c')
        assert a != ow._auth_digest('pw2', 's', 'c')


class TestSubscriptions:
    def test_mask_is_narrow_never_all(self):
        # General|Scenes|Inputs|Transitions|Outputs|SceneItems
        assert ow.EVENT_SUBS == 221
        # the two firehoses must NOT be subscribed
        assert not ow.EVENT_SUBS & (1 << 16)    # InputVolumeMeters
        assert not ow.EVENT_SUBS & (1 << 19)    # SceneItemTransformChanged


class TestRequest:
    def test_round_trip_and_frame_shape(self, monkeypatch):
        ws = FakeWs()
        monkeypatch.setattr(ow, '_ws', ws)
        _serve_reply(lambda rid: _ok(rid, {'sceneName': 'Kara'}))
        data = ow.request('GetSceneList', {'x': 1}, timeout=2)
        assert data == {'sceneName': 'Kara'}
        frame = ws.sent[0]
        assert frame['op'] == 6
        assert frame['d']['requestType'] == 'GetSceneList'
        assert frame['d']['requestData'] == {'x': 1}
        assert frame['d']['requestId']
        assert ow._pending == {}                  # slot cleaned up

    def test_rejected_carries_code(self, monkeypatch):
        monkeypatch.setattr(ow, '_ws', FakeWs())
        _serve_reply(lambda rid: _err(rid, 600, 'no such scene'))
        with pytest.raises(ow.ObsRejected) as exc:
            ow.request('SetCurrentProgramScene', {'sceneName': 'gone'}, timeout=2)
        assert exc.value.code == 600
        assert 'no such scene' in exc.value.comment
        assert ow._pending == {}

    def test_not_connected(self, monkeypatch):
        monkeypatch.setattr(ow, '_state', 'reconnecting')
        with pytest.raises(ow.ObsUnavailable):
            ow.request('GetSceneList', timeout=0.1)

    def test_send_failure(self, monkeypatch):
        ws = FakeWs()
        ws.fail = True
        monkeypatch.setattr(ow, '_ws', ws)
        with pytest.raises(ow.ObsUnavailable):
            ow.request('GetSceneList', timeout=0.1)
        assert ow._pending == {}

    def test_reply_timeout(self, monkeypatch):
        monkeypatch.setattr(ow, '_ws', FakeWs())
        with pytest.raises(ow.ObsUnavailable):
            ow.request('GetSceneList', timeout=0.05)
        assert ow._pending == {}


class TestSwitchScene:
    def test_sets_program_scene_and_updates_cache(self, monkeypatch):
        ws = FakeWs()
        monkeypatch.setattr(ow, '_ws', ws)
        _serve_reply(lambda rid: _ok(rid))
        assert ow.switch_scene('Kara Cam', timeout=2) == 'Kara Cam'
        assert ws.sent[0]['d']['requestType'] == 'SetCurrentProgramScene'
        assert ws.sent[0]['d']['requestData'] == {'sceneName': 'Kara Cam'}
        # optimistic cache update, confirmed later by the event
        assert ow.current_state()['current_scene'] == 'Kara Cam'

    def test_studio_mode_is_not_used(self, monkeypatch):
        """The DM does not use studio mode — we cut program directly and must
        never send SetCurrentPreviewScene/TriggerStudioModeTransition."""
        ws = FakeWs()
        monkeypatch.setattr(ow, '_ws', ws)
        _serve_reply(lambda rid: _ok(rid))
        ow.switch_scene('Kara Cam', timeout=2)
        types = [f['d']['requestType'] for f in ws.sent]
        assert 'SetCurrentPreviewScene' not in types
        assert 'TriggerStudioModeTransition' not in types


class TestEventCache:
    def test_program_scene_change_updates_cache(self):
        ow._dispatch({'op': 5, 'd': {'eventType': 'CurrentProgramSceneChanged',
                                     'eventData': {'sceneName': 'Group Shot'}}})
        assert ow.current_state()['current_scene'] == 'Group Shot'

    def test_scene_list_replaces_and_sorts_reverse_index(self):
        # OBS returns sceneIndex 0 as the BOTTOM entry; the dropdown should
        # read like the OBS panel, i.e. highest index first.
        ow._dispatch({'op': 5, 'd': {'eventType': 'SceneListChanged', 'eventData': {
            'scenes': [{'sceneName': 'Bottom', 'sceneIndex': 0},
                       {'sceneName': 'Top', 'sceneIndex': 2},
                       {'sceneName': 'Middle', 'sceneIndex': 1}]}}})
        assert ow.current_state()['scenes'] == ['Top', 'Middle', 'Bottom']
        ow._dispatch({'op': 5, 'd': {'eventType': 'SceneListChanged', 'eventData': {
            'scenes': [{'sceneName': 'Only', 'sceneIndex': 0}]}}})
        assert ow.current_state()['scenes'] == ['Only']      # replaced, not merged

    def test_scene_rename_follows_mapping_and_current(self):
        ow._dispatch({'op': 5, 'd': {'eventType': 'SceneListChanged', 'eventData': {
            'scenes': [{'sceneName': 'Old', 'sceneIndex': 0}]}}})
        ow._dispatch({'op': 5, 'd': {'eventType': 'CurrentProgramSceneChanged',
                                     'eventData': {'sceneName': 'Old'}}})
        ow._dispatch({'op': 5, 'd': {'eventType': 'SceneNameChanged', 'eventData': {
            'oldSceneName': 'Old', 'sceneName': 'New'}}})
        snap = ow.current_state()
        assert snap['scenes'] == ['New'] and snap['current_scene'] == 'New'

    def test_record_and_stream_state(self):
        ow._dispatch({'op': 5, 'd': {'eventType': 'RecordStateChanged',
                                     'eventData': {'outputActive': True}}})
        ow._dispatch({'op': 5, 'd': {'eventType': 'StreamStateChanged',
                                     'eventData': {'outputActive': True}}})
        snap = ow.current_state()
        assert snap['recording'] is True and snap['streaming'] is True

    def test_exit_started_breaks_the_session(self):
        with pytest.raises(ow._ObsExiting):
            ow._dispatch({'op': 5, 'd': {'eventType': 'ExitStarted', 'eventData': {}}})

    def test_response_frame_resolves_pending_not_events(self, monkeypatch):
        slot = {'evt': threading.Event(), 'reply': None}
        monkeypatch.setattr(ow, '_pending', {'42': slot})
        ow._dispatch(_ok('42', {'ok': 1}))
        assert slot['evt'].is_set() and slot['reply']['d']['requestId'] == '42'


class TestPriming:
    def test_apply_primed_fills_cache(self):
        ow._apply_primed('GetVersion', {'obsVersion': '30.1.2',
                                        'obsWebSocketVersion': '5.5.0'})
        ow._apply_primed('GetSceneList', {'currentProgramSceneName': 'Group',
                                          'scenes': [{'sceneName': 'Group', 'sceneIndex': 0}]})
        ow._apply_primed('GetRecordStatus', {'outputActive': False})
        ow._apply_primed('GetStudioModeEnabled', {'studioModeEnabled': True})
        snap = ow.current_state()
        assert snap['obs_version'] == '30.1.2'
        assert snap['current_scene'] == 'Group' and snap['scenes'] == ['Group']
        assert snap['recording'] is False and snap['studio_mode'] is True


class TestBackoff:
    def test_doubles_and_caps(self):
        assert ow._next_backoff(2) == 4
        assert ow._next_backoff(8) == 16
        assert ow._next_backoff(16) == ow._BACKOFF_MAX_S
        assert ow._next_backoff(ow._BACKOFF_MAX_S) == ow._BACKOFF_MAX_S


class TestLifecycle:
    def test_start_is_idempotent(self, monkeypatch):
        made = []

        class FakeThread:
            def __init__(self, *a, **kw):
                made.append(kw.get('name'))
                self._alive = True

            def start(self):
                pass

            def is_alive(self):
                return self._alive

        monkeypatch.setattr(ow.threading, 'Thread', FakeThread)
        monkeypatch.setattr(ow, '_thread', None)
        ow.start(object())
        ow.start(object())
        assert made == ['obs-ws']

    def test_unsupported_without_websocket_client(self, monkeypatch):
        """No websocket-client: mark unsupported and EXIT the loop — never spin."""
        import builtins
        monkeypatch.setattr(ow, '_cfg', lambda: {'host': 'h', 'port': 4455, 'password': ''})
        monkeypatch.setattr(ow, '_state', 'disabled')
        real_import = builtins.__import__

        def fake_import(name, *a, **kw):
            if name == 'websocket':
                raise ImportError('no websocket-client')
            return real_import(name, *a, **kw)

        monkeypatch.setattr(builtins, '__import__', fake_import)
        ow._stop.clear()
        ow._run()                      # returns rather than looping
        assert ow.state() == 'unsupported'

    def test_connected_reflects_state(self, monkeypatch):
        monkeypatch.setattr(ow, '_state', 'connected')
        assert ow.connected() is True
        monkeypatch.setattr(ow, '_state', 'auth_failed')
        assert ow.connected() is False
