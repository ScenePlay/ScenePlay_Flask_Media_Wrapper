"""_send_small transport routing: WS when connected, HTTP fallback (same
attempt on a mid-flight WS death), WsRejected treated as a permanent 4xx."""
import sys
import types

import pytest

import relay_broadcaster as rb
import relay_ws


CFG = {'url': 'http://relay', 'secret': 's', 'session_id': 'sid'}


@pytest.fixture()
def stub(monkeypatch):
    """Stub relay_ws module state + record _post calls."""
    calls = {'ws': [], 'http': []}

    def fake_post(path, payload, cfg, timeout=5):
        calls['http'].append((path, payload))
        return 'http-resp'
    monkeypatch.setattr(rb, '_post', fake_post)
    return calls


def test_ws_when_connected(monkeypatch, stub):
    monkeypatch.setattr(relay_ws, '_state', 'connected')
    monkeypatch.setattr(relay_ws, 'request',
                        lambda t, p, timeout=5: stub['ws'].append((t, p)) or {'ok': True})
    rb._send_small('token_move', {'x': 1}, '/api/v1/token/move', CFG)
    assert stub['ws'] == [('token_move', {'x': 1})]
    assert stub['http'] == []


def test_http_when_disconnected(monkeypatch, stub):
    monkeypatch.setattr(relay_ws, '_state', 'reconnecting')
    rb._send_small('token_move', {'x': 1}, '/api/v1/token/move', CFG)
    assert stub['http'] == [('/api/v1/token/move', {'x': 1})]


def test_ws_death_falls_through_same_attempt(monkeypatch, stub):
    monkeypatch.setattr(relay_ws, '_state', 'connected')

    def dying_request(t, p, timeout=5):
        raise relay_ws.WsUnavailable('died mid-send')
    monkeypatch.setattr(relay_ws, 'request', dying_request)
    rb._send_small('roll', {'r': 20}, '/api/v1/session/sid/push-roll', CFG)
    assert stub['http'] == [('/api/v1/session/sid/push-roll', {'r': 20})]


def test_ws_rejected_propagates_as_permanent(monkeypatch, stub):
    monkeypatch.setattr(relay_ws, '_state', 'connected')

    def rejecting(t, p, timeout=5):
        raise relay_ws.WsRejected(404, 'unknown session')
    monkeypatch.setattr(relay_ws, 'request', rejecting)
    with pytest.raises(relay_ws.WsRejected) as exc:
        rb._send_small('led', {}, '/api/v1/session/sid/led', CFG)
    assert rb._is_permanent(exc.value) is True
    assert stub['http'] == []                    # no HTTP retry for a 4xx


def test_ws_rejected_5xx_is_not_permanent():
    assert rb._is_permanent(relay_ws.WsRejected(500)) is False
    assert rb._is_permanent(relay_ws.WsRejected(422)) is True
