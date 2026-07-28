"""relay_ws client internals: request/reply correlation, error mapping,
caches, hello/map-summary adaptation, ack fallback. Pure tests — no sockets;
the reader thread is simulated by resolving _pending slots directly."""
import json
import threading

import pytest

import relay_ws as rw


@pytest.fixture(autouse=True)
def clean_state(monkeypatch):
    monkeypatch.setattr(rw, '_state', 'connected')
    monkeypatch.setattr(rw, '_pending', {})
    rw._presence_cache.clear()
    with rw._rolls_lock:
        rw._rolls_cache.clear()
    yield


class FakeWs:
    def __init__(self):
        self.sent = []
        self.fail = False

    def send(self, raw):
        if self.fail:
            raise OSError('broken pipe')
        self.sent.append(json.loads(raw))


def _serve_reply(reply_builder, delay=0.01):
    """Background 'reader': answers the next pending request."""
    def run():
        import time
        time.sleep(delay)
        for mid, slot in list(rw._pending.items()):
            slot['reply'] = reply_builder(mid)
            slot['evt'].set()
    t = threading.Thread(target=run, daemon=True)
    t.start()
    return t


class TestRequest:
    def test_round_trip(self, monkeypatch):
        ws = FakeWs()
        monkeypatch.setattr(rw, '_ws', ws)
        _serve_reply(lambda mid: {'id': mid, 'ok': True, 'seq': 7})
        reply = rw.request('led', {'patterns': []}, timeout=2)
        assert reply['seq'] == 7
        assert ws.sent[0]['type'] == 'led'
        assert rw._pending == {}                    # slot cleaned up

    def test_not_connected_raises_unavailable(self, monkeypatch):
        monkeypatch.setattr(rw, '_state', 'reconnecting')
        with pytest.raises(rw.WsUnavailable):
            rw.request('roll', {}, timeout=0.1)

    def test_send_failure_raises_unavailable(self, monkeypatch):
        ws = FakeWs()
        ws.fail = True
        monkeypatch.setattr(rw, '_ws', ws)
        with pytest.raises(rw.WsUnavailable):
            rw.request('roll', {}, timeout=0.1)
        assert rw._pending == {}

    def test_timeout_raises_unavailable(self, monkeypatch):
        monkeypatch.setattr(rw, '_ws', FakeWs())
        with pytest.raises(rw.WsUnavailable):
            rw.request('roll', {}, timeout=0.05)
        assert rw._pending == {}

    def test_4xx_reply_raises_rejected(self, monkeypatch):
        monkeypatch.setattr(rw, '_ws', FakeWs())
        _serve_reply(lambda mid: {'id': mid, 'ok': False, 'status': 404,
                                  'error': 'unknown token'})
        with pytest.raises(rw.WsRejected) as exc:
            rw.request('token_move', {}, timeout=2)
        assert exc.value.status == 404

    def test_5xx_reply_raises_unavailable(self, monkeypatch):
        monkeypatch.setattr(rw, '_ws', FakeWs())
        _serve_reply(lambda mid: {'id': mid, 'ok': False, 'status': 500})
        with pytest.raises(rw.WsUnavailable):
            rw.request('token_move', {}, timeout=2)


class TestCaches:
    def test_presence_ages_with_time(self, monkeypatch):
        rw._update_presence({'Carl': 3.0})
        monkeypatch.setattr(rw.time, 'time', lambda: rw._presence_ts + 10)
        aged = rw.get_presence_cached()
        assert 12.9 < aged['Carl'] < 13.1

    def test_presence_change_add_remove(self):
        rw._apply_presence_change({'player_name': 'Carl', 'online': True})
        assert rw._presence_cache['Carl'] == 0.0
        rw._apply_presence_change({'player_name': 'Carl', 'online': False})
        assert 'Carl' not in rw._presence_cache

    def test_rolls_ring_dedup_and_since(self):
        rw._cache_roll({'id': 1, 'result': 5})
        rw._cache_roll({'id': 1, 'result': 5})     # dup ignored
        rw._cache_roll({'id': 2, 'result': 9})
        assert [r['id'] for r in rw.get_rolls_cached(0)] == [1, 2]
        assert [r['id'] for r in rw.get_rolls_cached(1)] == [2]

    def test_rolls_ring_capped(self):
        for i in range(150):
            rw._cache_roll({'id': i})
        assert len(rw.get_rolls_cached(-1)) == 100


class TestMapSummaryAdapter:
    def test_shapes(self):
        assert rw._map_state_from_summary(None) == (False, None, '')
        assert rw._map_state_from_summary({'token_ids': None, 'url': ''}) == (True, None, '')
        assert rw._map_state_from_summary({'token_ids': [1, '2'], 'url': '/b/x.png'}) \
            == (True, {1, 2}, '/b/x.png')


class TestAckFallback:
    def test_ws_ack_fire_and_forget(self, monkeypatch):
        ws = FakeWs()
        monkeypatch.setattr(rw, '_ws', ws)
        rw._ack([1, 2], {'url': 'http://x', 'secret': 's', 'session_id': 'sid'})
        assert ws.sent[0] == {'type': 'ack_mutations',
                              'payload': {'mutation_ids': [1, 2]}}

    def test_http_fallback_when_socket_dead(self, monkeypatch):
        monkeypatch.setattr(rw, '_ws', None)
        posted = {}

        class FakeRequests:
            @staticmethod
            def post(url, json=None, headers=None, timeout=None):
                posted.update(url=url, body=json)
        import sys
        monkeypatch.setitem(sys.modules, 'requests', FakeRequests)
        rw._ack([3], {'url': 'http://relay', 'secret': 's', 'session_id': 'sid'})
        assert posted['url'].endswith('/api/v1/session/sid/mutations/ack')
        assert posted['body'] == {'mutation_ids': [3]}


class TestStartIdempotent:
    def test_start_reuses_thread(self, monkeypatch):
        started = []

        class FakeThread:
            def __init__(self, **kw):
                started.append(kw)
                self._alive = False
            def start(self):
                self._alive = True
            def is_alive(self):
                return self._alive

        monkeypatch.setattr(rw.threading, 'Thread', FakeThread)
        monkeypatch.setattr(rw, '_thread', None)
        rw.start(app=object())
        rw.start(app=object())
        assert len(started) == 1
        rw._stop.set()
        monkeypatch.setattr(rw, '_thread', None)
