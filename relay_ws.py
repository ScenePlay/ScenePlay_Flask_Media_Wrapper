"""GM control WebSocket client — the Flask side of the persistent relay link.

While connected it REPLACES the relay_receiver 2 s poll (the receiver is
paused): the relay pushes player token moves, sheet mutations, rolls and
presence the instant they happen, and relay_broadcaster routes its small
pushes (token moves, HP, conditions, rolls, LED/WLED) through request()
instead of one HTTPS POST each. Everything heavy or lifecycle-shaped stays
on HTTP, and any WS problem falls back to the poll automatically:

    DISABLED ──start()──▶ CONNECTING ──hello applied──▶ CONNECTED
       ▲                   │       ▲                        │
     stop()          403/404/405   └── backoff ──┐    drop/send-fail
       │                   ▼                     │          │
       └────────────── UNSUPPORTED         RECONNECTING ◀───┘
                       (this run keeps      (receiver resumed FIRST;
                        the 2 s poll)        polling covers the gap)

Invariants: the legacy receiver polls in every state except CONNECTED;
CONNECTED is entered only after the hello replay is committed; leaving it
resumes polling before anything else. Poll/WS overlap double-delivery is
safe because BOTH transports run the receiver's idempotent apply functions
(seq watermark, roll-id dedup, mutation ledger) — never duplicate them.

ZERO side effects at import: the forked music worker imports
relay_broadcaster, which lazily imports this module — in that process
start() never runs, connected() is False, and its pushes stay on HTTP.

Client idioms copied from relay_audio_stream._push_ws / _ws_drain:
X-Relay-Secret handshake header, 403/404/405 ⇒ unsupported, and the reader
must keep recv()ing (timeouts are ROUTINE) so the library answers server
pings — a deaf socket dies on the server's ping-timeout clock.
"""
import itertools
import json
import logging
import threading
import time

log = logging.getLogger(__name__)

_RECV_TIMEOUT_S = 5          # routine; keeps the lib pumping ping/pong
_HELLO_TIMEOUT_S = 20
_BACKOFF_MAX_S = 30
_HEALTHY_RUN_S = 60          # a run this long resets the backoff

_lock = threading.Lock()     # guards _ws sends + state transitions
_thread = None
_stop = threading.Event()
_wakeup = threading.Event()  # interrupts backoff sleeps (stop/restart)
_restart_requested = False
_state = 'disabled'          # disabled|connecting|connected|reconnecting|unsupported
_ws = None
_app = None
_msg_ids = itertools.count(1)
_pending = {}                # id -> {'evt': Event, 'reply': dict|None}

# Local caches fed by relay events (serve the browser widget polls without a
# blocking relay GET while connected).
_presence_cache = {}         # {player_name: seconds_since_seen}
_presence_ts = 0.0
_rolls_cache = []            # roll_log-shaped rows, ring of ~100
_rolls_lock = threading.Lock()


class WsUnavailable(Exception):
    """No usable socket right now — caller should fall back to HTTP."""


class WsRejected(Exception):
    """The relay answered ok:false with an HTTP-ish status."""
    def __init__(self, status, error=''):
        super().__init__(f'{status}: {error}')
        self.status = status


# ── public API ───────────────────────────────────────────────────────────────

def start(app):
    """Idempotent; safe to call at boot/enable. No-op in forked workers
    (they never call this, so connected() stays False there)."""
    global _thread, _app
    _app = app
    if _thread is not None and _thread.is_alive():
        _stop.clear()
        return
    _stop.clear()
    _wakeup.clear()
    _thread = threading.Thread(target=_run, daemon=True, name='relay-gm-ws')
    _thread.start()
    log.info('Relay GM WebSocket manager started')


def stop():
    global _state
    _stop.set()
    _wakeup.set()
    _close_socket()
    _set_state('disabled')


def restart():
    """Reconnect with fresh config (session regen / url / secret change).
    Also clears UNSUPPORTED — a new relay may support the WS."""
    global _restart_requested
    _restart_requested = True
    _wakeup.set()
    _close_socket()
    if _app is not None and (_thread is None or not _thread.is_alive()):
        start(_app)


def connected():
    return _state == 'connected'


def state():
    return _state


def request(msg_type, payload, timeout=5):
    """Send a request frame and wait for its correlated reply.

    Raises WsUnavailable when not connected / send fails / reply times out,
    WsRejected when the relay answered ok:false with a 4xx-ish status."""
    if _state != 'connected':
        raise WsUnavailable('not connected')
    mid = next(_msg_ids)
    slot = {'evt': threading.Event(), 'reply': None}
    _pending[mid] = slot
    try:
        _send({'id': mid, 'type': msg_type, 'payload': payload})
        if not slot['evt'].wait(timeout):
            raise WsUnavailable('reply timeout')
        reply = slot['reply'] or {}
        if not reply.get('ok'):
            status = int(reply.get('status') or 500)
            if 400 <= status < 500:
                raise WsRejected(status, reply.get('error', ''))
            raise WsUnavailable(f'relay error {status}')
        return reply
    finally:
        _pending.pop(mid, None)


def get_presence_cached():
    """Age-adjusted presence snapshot from the last relay event."""
    age = time.time() - _presence_ts
    return {name: secs + age for name, secs in _presence_cache.items()}


def get_rolls_cached(since_id):
    with _rolls_lock:
        return [r for r in _rolls_cache if (r.get('id') or 0) > since_id]


# ── internals ────────────────────────────────────────────────────────────────

def _set_state(new):
    global _state
    if _state != new:
        log.info('Relay GM WebSocket: %s -> %s', _state, new)
        _state = new


def _cfg():
    from sql import appsettingGet
    enabled = appsettingGet('relay_enabled', '0')
    url     = appsettingGet('relay_url', '')
    secret  = appsettingGet('relay_secret', '')
    sid     = appsettingGet('relay_session_id', '')
    if enabled != '1' or not url or not sid:
        return None
    return {'url': url, 'secret': secret, 'session_id': sid}


def _close_socket():
    global _ws
    with _lock:
        if _ws is not None:
            try:
                _ws.close()
            except Exception:
                pass
            _ws = None


def _send(frame):
    with _lock:
        ws = _ws
        if ws is None:
            raise WsUnavailable('socket closed')
        try:
            ws.send(json.dumps(frame))
        except Exception as exc:
            raise WsUnavailable(str(exc))


def _fail_pending():
    for slot in list(_pending.values()):
        slot['evt'].set()


def _run():
    global _ws, _restart_requested
    import relay_receiver
    backoff = 2
    while not _stop.is_set():
        _restart_requested = False
        cfg = _cfg()
        if cfg is None:
            _set_state('disabled')
            _wakeup.wait(5)
            _wakeup.clear()
            continue

        try:
            import websocket
        except ImportError:
            _set_state('unsupported')
            log.warning('websocket-client not installed — GM link stays on polling')
            return

        ws_url = (cfg['url'].rstrip('/')
                  .replace('https://', 'wss://', 1).replace('http://', 'ws://', 1)
                  + f"/api/v1/session/{cfg['session_id']}/gm-ws")
        _set_state('connecting' if _state in ('disabled', 'connecting',
                                              'unsupported') else 'reconnecting')
        started = time.monotonic()
        try:
            ws = websocket.create_connection(
                ws_url, timeout=_RECV_TIMEOUT_S,
                header={'X-Relay-Secret': cfg['secret']})
        except websocket.WebSocketBadStatusException as exc:
            if getattr(exc, 'status_code', 0) in (403, 404, 405):
                # relay predates the gm-ws route (or auth is broken, which the
                # HTTP path will report properly) — polling for the rest of
                # the run; restart() clears this.
                _set_state('unsupported')
                log.info('Relay has no GM WebSocket — staying on the 2s poll')
                if not _wait_for_restart():
                    return
                continue
            _sleep_backoff(backoff)
            backoff = min(_BACKOFF_MAX_S, backoff * 2)
            continue
        except Exception as exc:
            log.info('GM WebSocket connect failed (%s); retry in %ss', exc, backoff)
            _sleep_backoff(backoff)
            backoff = min(_BACKOFF_MAX_S, backoff * 2)
            continue

        with _lock:
            _ws = ws
        try:
            _session_loop(ws, cfg)
        except Exception as exc:
            log.info('GM WebSocket session ended: %s', exc)
        finally:
            # LEAVING CONNECTED: resume polling before anything else so no
            # window exists where neither transport is running.
            import relay_receiver as rr
            rr.resume()
            _close_socket()
            _fail_pending()
            if not _stop.is_set():
                _set_state('reconnecting')
        if time.monotonic() - started > _HEALTHY_RUN_S:
            backoff = 2                     # long healthy run: fast reconnect
        if not _stop.is_set() and not _restart_requested:
            _sleep_backoff(backoff)
            backoff = min(_BACKOFF_MAX_S, backoff * 2)
    _set_state('disabled')


def _wait_for_restart():
    """Park in UNSUPPORTED until restart()/stop(). True = keep looping."""
    while not _stop.is_set():
        _wakeup.wait(3600)
        _wakeup.clear()
        if _restart_requested:
            return True
    return False


def _sleep_backoff(seconds):
    _wakeup.wait(seconds)
    _wakeup.clear()


def _session_loop(ws, cfg):
    """One connected session: hello replay, then the event pump."""
    import websocket
    import relay_receiver as rr

    # hello must arrive first; apply it BEFORE claiming CONNECTED
    deadline = time.monotonic() + _HELLO_TIMEOUT_S
    hello = None
    while time.monotonic() < deadline:
        try:
            frame = json.loads(ws.recv())
        except websocket.WebSocketTimeoutException:
            continue
        if frame.get('type') == 'hello':
            hello = frame.get('data') or {}
            break
    if hello is None:
        raise RuntimeError('no hello within timeout')

    with _app.app_context():
        _apply_hello(hello, cfg)

    rr.pause()
    _set_state('connected')
    log.info('GM WebSocket connected — polling paused')

    while not _stop.is_set() and not _restart_requested:
        try:
            raw = ws.recv()
        except websocket.WebSocketTimeoutException:
            continue                        # routine: keeps ping/pong pumping
        if raw is None or raw == '':
            raise RuntimeError('socket closed by relay')
        try:
            frame = json.loads(raw)
        except (ValueError, TypeError):
            continue
        if frame.get('id') is not None:     # correlated request reply
            slot = _pending.get(frame['id'])
            if slot is not None:
                slot['reply'] = frame
                slot['evt'].set()
            continue
        with _app.app_context():
            _handle_event(frame, cfg)


def _apply_hello(hello, cfg):
    """Connect/reconnect replay through the receiver's idempotent appliers."""
    import relay_receiver as rr

    tokens = hello.get('tokens') or []
    map_summary = hello.get('map_summary')
    map_state = _map_state_from_summary(map_summary)
    rr.apply_relay_tokens(tokens, map_state)
    rr.ingest_relay_rolls(hello.get('roll_log') or [])

    pending = hello.get('pending_mutations') or []
    applied = rr.apply_relay_mutations(pending, cfg['url'], cfg['session_id'])
    if applied:
        _ack(applied, cfg)

    _update_presence(hello.get('presence') or {})
    rr.note_sync_ok()


def _handle_event(frame, cfg):
    import relay_receiver as rr
    ftype = frame.get('type')
    data = frame.get('data') or {}
    try:
        if ftype == 'token_move':
            rr.apply_relay_tokens([data], None)
        elif ftype == 'mutation':
            applied = rr.apply_relay_mutations([data], cfg['url'], cfg['session_id'])
            if applied:
                _ack(applied, cfg)
        elif ftype == 'roll_result':
            rr.ingest_relay_rolls([data])
            _cache_roll(data)
        elif ftype == 'presence':
            _update_presence(data)
        elif ftype == 'presence_change':
            _apply_presence_change(data)
        elif ftype == 'sync_hint':
            # periodic reconciliation: tokens + the map self-heal watchdog
            map_state = _map_state_from_summary(data.get('map_summary'))
            rr.apply_relay_tokens(data.get('tokens') or [], map_state)
        elif ftype == 'health_update':
            pass    # local is HP authority; hp arrives as an hp_delta mutation
        rr.note_sync_ok()
    except Exception as exc:
        log.warning('GM WebSocket event %s failed: %s', ftype, exc)
        try:
            from extensions import db
            db.session.rollback()
        except Exception:
            pass


def _map_state_from_summary(summary):
    """Adapt a gm-ws map_summary to relay_receiver's (present, ids, url)."""
    if summary is None:
        return (False, None, '')
    ids = summary.get('token_ids')
    try:
        ids = {int(i) for i in ids} if ids is not None else None
    except (TypeError, ValueError):
        ids = None
    return (True, ids, summary.get('url') or '')


def _ack(applied_ids, cfg):
    """Ack over the socket FIRE-AND-FORGET (this runs on the reader thread,
    which cannot block waiting for its own reply frame); on a send failure
    fall back to the HTTP ack. Either way, at-least-once is preserved: an
    unacked mutation is re-served in the next hello and the local ledger
    skips-but-re-acks it, so double-apply is impossible."""
    try:
        _send({'type': 'ack_mutations', 'payload': {'mutation_ids': applied_ids}})
        return
    except Exception:
        pass
    try:
        import requests
        requests.post(
            cfg['url'].rstrip('/') +
            f"/api/v1/session/{cfg['session_id']}/mutations/ack",
            json={'mutation_ids': applied_ids},
            headers={'X-Relay-Secret': cfg['secret'],
                     'Content-Type': 'application/json'},
            timeout=5,
        )
    except Exception as exc:
        log.warning('Mutation ack failed over WS and HTTP: %s', exc)


def _update_presence(presence):
    global _presence_ts
    _presence_cache.clear()
    _presence_cache.update(presence or {})
    _presence_ts = time.time()


def _apply_presence_change(data):
    global _presence_ts
    name = data.get('player_name')
    if not name:
        return
    if data.get('online'):
        _presence_cache[name] = 0.0
    else:
        _presence_cache.pop(name, None)
    _presence_ts = time.time()


def _cache_roll(row):
    with _rolls_lock:
        if any((r.get('id') or 0) == (row.get('id') or -1) for r in _rolls_cache):
            return
        _rolls_cache.append(row)
        del _rolls_cache[:-100]
