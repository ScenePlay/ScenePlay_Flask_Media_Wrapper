"""OBS Studio control — the Flask side of the obs-websocket v5 link.

Lets the DM put a player on screen from ScenePlay: click a party member on the
battle map and OBS cuts its program scene to that player's camera. The socket
is persistent, so the click path never pays a connect cost:

    DISABLED ──start()──▶ CONNECTING ──hello──▶ IDENTIFYING ──primed──▶ CONNECTED
       ▲                     │   ▲                  │                       │
     stop()            refused/  └─── backoff ──┐   │ closed before      drop /
       │                  error                 │   ▼  Identified       send-fail
       │                     ▼                  │                           │
       └──────────────── UNSUPPORTED      RECONNECTING ◀── AUTH_FAILED ◀─────┘
                    (no websocket-client,   (backoff)   (parked until restart)
                     or rpcVersion != 1)

UNSUPPORTED and AUTH_FAILED *park* until restart(): retrying a bad password
every couple of seconds spams the OBS log and can trip its ban logic. OBS
simply not being open is the NORMAL case — that backs off quietly.

Requests are synchronous request/reply, deliberately NOT a relay_broadcaster
style push queue. The DM needs a confirmable answer ("did it cut?"), a
sleeping OBS costs nothing because connected() is an in-memory check made
BEFORE issuing, and commands must not be coalesced or retried the way state
pushes are (StartRecord then StopRecord are both required, in order, and a
scene switch retried a minute later would yank program back).

Cached state (current scene, scene list, record/stream) is primed once on
identify and then kept fresh BY EVENTS, so the battle map's 2 s poll reads
memory and never round-trips to OBS. It also means a scene the DM switches
inside OBS shows up in ScenePlay within one poll.

ZERO side effects at import — app.py is re-imported by forkserver children,
and nothing on the forked music-worker path may drag this module in.

Client idioms copied from relay_ws: the reader thread must keep recv()ing
(timeouts are ROUTINE) so the library answers pings, and it must NEVER call
request() — it would block waiting for a reply only it can deliver.
"""
import base64
import hashlib
import itertools
import json
import logging
import threading
import time

log = logging.getLogger(__name__)

_RECV_TIMEOUT_S = 5          # routine; keeps the lib pumping ping/pong
_HELLO_TIMEOUT_S = 10
_PRIME_TIMEOUT_S = 10
_BACKOFF_MAX_S = 30
_HEALTHY_RUN_S = 60          # a run this long resets the backoff
_RPC_VERSION = 1
DEFAULT_HOST = '127.0.0.1'
DEFAULT_PORT = 4455

# Event subscriptions, narrow ON PURPOSE. General|Scenes|Inputs|Transitions|
# Outputs|SceneItems. Never "All": that adds InputVolumeMeters and
# SceneItemTransformChanged, which fire tens of times a second.
EVENT_SUBS = 1 | 4 | 8 | 16 | 64 | 128     # 221

_lock = threading.Lock()     # guards _ws sends + state transitions
_thread = None
_stop = threading.Event()
_wakeup = threading.Event()  # interrupts backoff sleeps (stop/restart)
_restart_requested = False
_state = 'disabled'          # disabled|connecting|identifying|connected|
                             # reconnecting|auth_failed|unsupported
_ws = None
_app = None
_req_ids = itertools.count(1)
_pending = {}                # requestId(str) -> {'evt': Event, 'reply': dict|None}

_cache_lock = threading.Lock()


def _blank_cache():
    return {
        'current_scene': '',
        'scenes': [],
        'transitions': [],
        'current_transition': '',
        'transition_ms': 0,
        'studio_mode': False,
        'recording': False,
        'streaming': False,
        'record_timecode': '',
        'stream_timecode': '',
        'obs_version': '',
        'ws_version': '',
        'base_width': 1920,
        'base_height': 1080,
        'input_kinds': [],
    }


_cache = _blank_cache()


class ObsUnavailable(Exception):
    """No usable socket right now — not connected, send failed, or timed out."""


class ObsRejected(Exception):
    """OBS answered requestStatus.result == false."""
    def __init__(self, code, comment=''):
        super().__init__(f'{code}: {comment}' if comment else str(code))
        self.code = int(code or 0)
        self.comment = comment or ''


# ── public API ───────────────────────────────────────────────────────────────

def start(app):
    """Idempotent; safe to call at boot and from the enable button."""
    global _thread, _app
    _app = app
    if _thread is not None and _thread.is_alive():
        _stop.clear()
        return
    _stop.clear()
    _wakeup.clear()
    _thread = threading.Thread(target=_run, daemon=True, name='obs-ws')
    _thread.start()
    log.info('OBS WebSocket manager started')


def stop():
    _stop.set()
    _wakeup.set()
    _close_socket()
    _set_state('disabled')


def restart():
    """Reconnect with fresh config (host/port/password change). Also clears
    AUTH_FAILED / UNSUPPORTED — the new settings may well work."""
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


def current_state():
    """In-memory snapshot — no OBS round trip. Safe on the 2 s poll path."""
    with _cache_lock:
        snap = dict(_cache)
        snap['scenes'] = list(_cache['scenes'])
        snap['transitions'] = [dict(t) for t in _cache['transitions']]
        snap['input_kinds'] = list(_cache.get('input_kinds') or [])
    snap['connected'] = connected()
    snap['state'] = _state
    return snap


def request(request_type, data=None, timeout=3):
    """Send one request and wait for its correlated reply.

    Raises ObsUnavailable (not connected / send failed / timed out) or
    ObsRejected (OBS said no). Returns responseData, possibly {}."""
    if _state != 'connected':
        raise ObsUnavailable('OBS not connected')
    return _request_locked(request_type, data, timeout)


def scene_list(refresh=False):
    """(scenes, current_scene). Cached unless refresh — the Broadcast page's
    poll must not hammer OBS."""
    if refresh and connected():
        try:
            _apply_scene_list(request('GetSceneList'))
        except (ObsUnavailable, ObsRejected) as exc:
            log.info('OBS scene list refresh failed: %s', exc)
    snap = current_state()
    return snap['scenes'], snap['current_scene']


def switch_scene(name, transition=None, duration_ms=None, timeout=3):
    """Cut OBS's PROGRAM scene. Studio mode is not used (see the module note
    in routes/obs.py); this sets program directly."""
    if transition:
        try:
            request('SetCurrentSceneTransition', {'transitionName': transition},
                    timeout=timeout)
            if duration_ms:
                # Fixed transitions (Cut) reject a duration — never fatal.
                _set_transition_duration(int(duration_ms), timeout)
        except ObsRejected as exc:
            log.info('OBS transition setup rejected (%s) — switching anyway', exc)
    request('SetCurrentProgramScene', {'sceneName': name}, timeout=timeout)
    # Optimistic; CurrentProgramSceneChanged confirms a beat later.
    with _cache_lock:
        _cache['current_scene'] = name
    _clear_error()
    return name


def last_error():
    """'ts|op|message' from the last failure, or '' once something succeeds."""
    from sql import appsettingGet
    return appsettingGet('obs_last_error', '') or ''


# ── scene building ────────────────────────────────────────────────────────────

# Browser-source flags that keep a camera feed CONNECTED while its scene is
# off-air. OBS would otherwise reload the page each time the scene goes live
# (restart_when_active) or destroy the source while it is hidden (shutdown);
# either way the feed has to renegotiate WebRTC on the cut back, which is the
# second or two of empty box seen when returning from the map to the party.
# The cost is that every camera stays connected all session, on-air or not.
KEEPALIVE = {'restart_when_active': False, 'shutdown': False}


def browser_kind():
    """The input kind for a browser source on THIS OBS build, or '' when the
    build has no browser plugin at all (then scene creation degrades to a
    clear error instead of a confusing rejection)."""
    with _cache_lock:
        kinds = list(_cache.get('input_kinds') or [])
    if 'browser_source' in kinds:
        return 'browser_source'
    for k in kinds:
        if 'browser' in k.lower():
            return k
    return ''


def create_player_scene(scene_name, source_name, url, timeout=5):
    """Build (or repair) a scene holding one player's video feed.

    Idempotent on purpose: 'already exists' is treated as REUSE at every step,
    so the DM can press the button again after changing a feed URL. Returns
    (scene_name, source_name, warnings) — a scene that exists but wasn't
    perfectly sized is still usable, so cosmetic failures are warnings rather
    than errors."""
    warnings = []
    kind = browser_kind()
    if not kind:
        raise ObsRejected(605, 'This OBS build has no browser source input')

    try:
        request('CreateScene', {'sceneName': scene_name}, timeout=timeout)
    except ObsRejected as exc:
        if exc.code != 601:                       # 601 = already exists
            raise
        warnings.append(f'Scene "{scene_name}" already existed — reused it.')

    with _cache_lock:
        width = _cache.get('base_width') or 1920
        height = _cache.get('base_height') or 1080

    settings = {'url': url, 'width': width, 'height': height,
                'reroute_audio': True, **KEEPALIVE}
    item_id = None
    try:
        res = request('CreateInput', {
            'sceneName': scene_name, 'inputName': source_name,
            'inputKind': kind, 'inputSettings': settings,
            'sceneItemEnabled': True}, timeout=timeout)
        item_id = res.get('sceneItemId')
    except ObsRejected as exc:
        if exc.code != 601:
            # Some browser plugins reject reroute_audio; the source is far
            # more useful without it than not at all.
            if 'reroute' in (exc.comment or '').lower():
                settings.pop('reroute_audio', None)
                res = request('CreateInput', {
                    'sceneName': scene_name, 'inputName': source_name,
                    'inputKind': kind, 'inputSettings': settings,
                    'sceneItemEnabled': True}, timeout=timeout)
                item_id = res.get('sceneItemId')
                warnings.append('This OBS build would not route the browser '
                                'source audio into OBS — the player\'s mic may '
                                'need routing by hand.')
            else:
                raise
        else:
            # Source already there: point it at the (possibly new) URL.
            set_browser_url(source_name, url, timeout=timeout)
            warnings.append(f'Source "{source_name}" already existed — '
                            f'pointed it at the current feed.')
            try:
                got = request('GetSceneItemId', {'sceneName': scene_name,
                                                 'sourceName': source_name},
                              timeout=timeout)
                item_id = got.get('sceneItemId')
            except ObsRejected:
                warnings.append('Could not find the source inside that scene — '
                                'check it is present in OBS.')

    if item_id is not None:
        try:
            request('SetSceneItemTransform', {
                'sceneName': scene_name, 'sceneItemId': item_id,
                'sceneItemTransform': {
                    'boundsType': 'OBS_BOUNDS_SCALE_INNER',
                    'boundsWidth': width, 'boundsHeight': height,
                    'boundsAlignment': 0, 'positionX': 0, 'positionY': 0}},
                timeout=timeout)
        except ObsRejected as exc:
            # Cosmetic only — never fail the whole build over sizing.
            warnings.append(f'Could not size the source to the canvas ({exc}).')

    _clear_error()
    return scene_name, source_name, warnings


# ── scene items (the party scene) ─────────────────────────────────────────────
# One camera = one INPUT, referenced into the party scene as a scene item.
# obs-websocket lets a single input appear in many scenes with independent
# transforms, so featuring a player is a transform change — never a re-create,
# and never a program cut.

def ensure_scene(scene_name, timeout=3):
    """Create the scene unless it already exists. Returns True if created."""
    try:
        request('CreateScene', {'sceneName': scene_name}, timeout=timeout)
        return True
    except ObsRejected as exc:
        if exc.code == 601:            # already exists — that's the happy path
            return False
        raise


def scene_items(scene_name, timeout=3):
    """{source_name: sceneItemId} for everything currently in the scene."""
    data = request('GetSceneItemList', {'sceneName': scene_name}, timeout=timeout)
    out = {}
    for item in data.get('sceneItems') or []:
        name = item.get('sourceName')
        if name:
            out[name] = item.get('sceneItemId')
    return out


def ensure_browser_input(scene_name, source_name, url, width, height, timeout=5,
                         rewrite_settings=True):
    """Make sure a browser source exists AND is in this scene.

    Three cases, all idempotent: brand new; input exists elsewhere (add it to
    this scene without duplicating the input); already here (just repoint the
    URL). Returns (sceneItemId, warnings).

    rewrite_settings=False skips the settings write for an input that already
    exists, leaving the running page completely alone. Pass it when the caller
    knows the url and size are unchanged: writing them re-renders the page even
    when nothing differs, which blanks a live camera for a moment."""
    warnings = []
    kind = browser_kind()
    if not kind:
        raise ObsRejected(605, 'This OBS build has no browser source input')

    settings = {'url': url, 'width': int(width), 'height': int(height),
                'reroute_audio': True, **KEEPALIVE}
    try:
        res = request('CreateInput', {
            'sceneName': scene_name, 'inputName': source_name,
            'inputKind': kind, 'inputSettings': settings,
            'sceneItemEnabled': True}, timeout=timeout)
        return res.get('sceneItemId'), warnings
    except ObsRejected as exc:
        if exc.code != 601:
            if 'reroute' in (exc.comment or '').lower():
                settings.pop('reroute_audio', None)
                res = request('CreateInput', {
                    'sceneName': scene_name, 'inputName': source_name,
                    'inputKind': kind, 'inputSettings': settings,
                    'sceneItemEnabled': True}, timeout=timeout)
                warnings.append("This OBS build would not route browser audio "
                                "into OBS — mics may need routing by hand.")
                return res.get('sceneItemId'), warnings
            raise

    # The input already exists somewhere. Point it at the current URL, RESIZE
    # it, and make sure THIS scene holds a reference to it.
    #
    # The resize matters: a browser input keeps the resolution it was created
    # with, and place_item uses SCALE_INNER bounds — which preserve aspect
    # ratio. So an input still rendering at its old size gets letterboxed
    # inside its new box instead of filling it, and the item ends up visibly
    # shorter (or narrower) than asked for. Only re-rendering it at the right
    # resolution makes the bounds an exact fit.
    # KEEPALIVE goes on here too, not just at create time: sources built by an
    # earlier version still carry restart_when_active, so "Build / refresh
    # party scene" is what repairs an existing setup.
    if rewrite_settings:
        request('SetInputSettings',
                {'inputName': source_name,
                 'inputSettings': {'url': url, 'width': int(width),
                                   'height': int(height), **KEEPALIVE},
                 'overlay': True}, timeout=timeout)
    try:
        item_id = scene_items(scene_name, timeout=timeout).get(source_name)
    except ObsRejected:
        item_id = None
    if item_id is None:
        res = request('CreateSceneItem', {
            'sceneName': scene_name, 'sourceName': source_name,
            'sceneItemEnabled': True}, timeout=timeout)
        item_id = res.get('sceneItemId')
    return item_id, warnings


def place_item(scene_name, item_id, rect, timeout=3):
    """Position/size one tile. Bounds (not scale) so the source fills its cell
    regardless of the camera's own resolution."""
    request('SetSceneItemTransform', {
        'sceneName': scene_name, 'sceneItemId': item_id,
        'sceneItemTransform': {
            'positionX': float(rect['x']), 'positionY': float(rect['y']),
            'boundsType': 'OBS_BOUNDS_SCALE_INNER',
            'boundsAlignment': 0,
            'boundsWidth': float(rect['w']), 'boundsHeight': float(rect['h']),
            'alignment': 5,                 # top-left, so position == the rect
            'cropLeft': 0, 'cropRight': 0, 'cropTop': 0, 'cropBottom': 0,
            'rotation': 0.0,
        }}, timeout=timeout)


# ── animated moves (the spotlight) ────────────────────────────────────────────
# Featuring a player reflows the whole grid. Snapping every tile to its new box
# in one frame reads as a glitch; easing them across reads as a camera move.

ANIM_FPS = 30                 # frames a second the ease is sampled at
_anim_lock = threading.Lock()
_anim_gen = 0


def _ease(t):
    """Ease-in-out cubic — starts and finishes gently, which is what makes the
    reflow look intentional rather than like a dropped frame."""
    return 4 * t ** 3 if t < 0.5 else 1 - ((-2 * t + 2) ** 3) / 2


def _send_batch(requests):
    """Fire a RequestBatch and do NOT wait for the reply.

    An animation frame carries one transform per tile and lands every ~30ms; a
    correlated round-trip each would cost far more than the move is worth, and
    a dropped frame is invisible because the next one supersedes it. _dispatch
    already ignores replies nobody is waiting on."""
    _send({'op': 8, 'd': {'requestId': str(next(_req_ids)),
                          'haltOnFailure': False, 'executionType': 0,
                          'requests': requests}})


def animate_items(scene_name, moves, duration_s=0.7, steps=None):
    """Ease scene items from one rect to another. Returns IMMEDIATELY — the
    frames go out from a background thread, so no HTTP handler waits on them.

    moves: [(item_id, from_rect, to_rect)] with rects as {'x','y','w','h'}.
    steps: frame count; derived from the duration at ANIM_FPS when omitted, so
    a longer move gets more frames instead of a chunkier one.

    A later call supersedes an in-flight one: hammering the number keys must
    not leave two animations fighting over the same tiles. The last frame is
    the exact target, so the scene always lands where it was asked to unless a
    NEWER move took over — which lands somewhere better."""
    moves = [(i, a, b) for i, a, b in moves if i is not None]
    if steps is None:
        steps = max(4, min(int(duration_s * ANIM_FPS), 90))
    if not moves or steps < 1 or duration_s <= 0:
        return
    global _anim_gen
    with _anim_lock:
        _anim_gen += 1
        gen = _anim_gen

    def run():
        delay = duration_s / steps
        for step in range(1, steps + 1):
            with _anim_lock:
                if gen != _anim_gen:
                    return              # a newer spotlight owns these tiles
            t = _ease(step / steps)
            reqs = [{'requestType': 'SetSceneItemTransform',
                     'requestData': {
                         'sceneName': scene_name, 'sceneItemId': item_id,
                         'sceneItemTransform': {
                             'positionX': a['x'] + (b['x'] - a['x']) * t,
                             'positionY': a['y'] + (b['y'] - a['y']) * t,
                             'boundsType': 'OBS_BOUNDS_SCALE_INNER',
                             'boundsAlignment': 0, 'alignment': 5,
                             'boundsWidth': max(a['w'] + (b['w'] - a['w']) * t, 1.0),
                             'boundsHeight': max(a['h'] + (b['h'] - a['h']) * t, 1.0),
                         }}}
                    for item_id, a, b in moves]
            try:
                _send_batch(reqs)
            except ObsUnavailable:
                return                  # link dropped; the next sync repairs it
            except Exception:
                log.exception('party tile animation failed')
                return
            if step < steps:
                time.sleep(delay)

    threading.Thread(target=run, name='obs-tile-anim', daemon=True).start()


def set_item_enabled(scene_name, item_id, enabled, timeout=3):
    request('SetSceneItemEnabled', {
        'sceneName': scene_name, 'sceneItemId': item_id,
        'sceneItemEnabled': bool(enabled)}, timeout=timeout)


def set_item_index(scene_name, item_id, index, timeout=3):
    """Z-order. The featured tile is raised so its scale-up draws OVER its
    neighbours instead of being clipped by them."""
    request('SetSceneItemIndex', {
        'sceneName': scene_name, 'sceneItemId': item_id,
        'sceneItemIndex': int(index)}, timeout=timeout)


def remove_item(scene_name, item_id, timeout=3):
    request('RemoveSceneItem', {'sceneName': scene_name,
                                'sceneItemId': item_id}, timeout=timeout)


def set_browser_url(source_name, url, timeout=3):
    """Repoint an existing browser source (the player changed their feed).
    Re-asserts KEEPALIVE so a source built by an earlier version stops
    reloading itself on every cut back to its scene."""
    request('SetInputSettings', {'inputName': source_name,
                                 'inputSettings': {'url': url, **KEEPALIVE},
                                 'overlay': True}, timeout=timeout)


def refresh_browser_source(source_name, timeout=3):
    """Force a reload — the player restarted their camera."""
    request('PressInputPropertiesButton',
            {'inputName': source_name, 'propertyName': 'refreshnocache'},
            timeout=timeout)


# ── internals ────────────────────────────────────────────────────────────────

def _set_state(new):
    global _state
    if _state != new:
        log.info('OBS WebSocket: %s -> %s', _state, new)
        _state = new


def _cfg():
    """Re-read fresh on every connect attempt so a settings change lands
    without a restart of the app."""
    from sql import appsettingGet
    if appsettingGet('obs_enabled', '0') != '1':
        return None
    # NB: appsettingGet's default only applies when the row is ABSENT — an
    # empty stored value would otherwise shadow it, so coerce here too.
    host = (appsettingGet('obs_host', '') or '').strip() or DEFAULT_HOST
    try:
        port = int((appsettingGet('obs_port', '') or '').strip() or DEFAULT_PORT)
    except (TypeError, ValueError):
        port = DEFAULT_PORT
    return {'host': host, 'port': port,
            'password': appsettingGet('obs_password', '') or ''}


def _auth_digest(password, salt, challenge):
    """obs-websocket v5 auth: b64(sha256(b64(sha256(password+salt)) + challenge)).

    Pure function — the unit test pins it against a hand-computed vector,
    because a wrong digest is indistinguishable from a wrong password."""
    secret = base64.b64encode(
        hashlib.sha256((password + salt).encode('utf-8')).digest()).decode()
    return base64.b64encode(
        hashlib.sha256((secret + challenge).encode('utf-8')).digest()).decode()


def _next_backoff(seconds):
    return min(_BACKOFF_MAX_S, seconds * 2)


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
            raise ObsUnavailable('socket closed')
        try:
            ws.send(json.dumps(frame))
        except Exception as exc:
            raise ObsUnavailable(str(exc))


def _fail_pending():
    for slot in list(_pending.values()):
        slot['evt'].set()


def _request_locked(request_type, data, timeout):
    rid = str(next(_req_ids))
    slot = {'evt': threading.Event(), 'reply': None}
    _pending[rid] = slot
    try:
        _send({'op': 6, 'd': {'requestType': request_type,
                              'requestId': rid,
                              'requestData': data or {}}})
        if not slot['evt'].wait(timeout):
            raise ObsUnavailable(f'{request_type}: reply timeout')
        return _unwrap(request_type, slot['reply'] or {})
    finally:
        _pending.pop(rid, None)


def _unwrap(request_type, reply):
    d = reply.get('d') or {}
    status = d.get('requestStatus') or {}
    if status.get('result'):
        return d.get('responseData') or {}
    raise ObsRejected(status.get('code'), status.get('comment', ''))


def _set_transition_duration(ms, timeout):
    try:
        request('SetCurrentSceneTransitionDuration',
                {'transitionDuration': ms}, timeout=timeout)
    except ObsRejected as exc:
        log.info('OBS rejected transition duration (fixed transition?): %s', exc)


def _record_error(op, exc):
    """Sticky telemetry for the DM banner, same shape as the relay's
    relay_push_last_drop."""
    try:
        from sql import appsettingSet
        ts = time.strftime('%Y-%m-%d %H:%M:%S')
        appsettingSet('obs_last_error', f'{ts}|{op}|{str(exc)[:120]}')
    except Exception:
        pass


def _clear_error():
    try:
        from sql import appsettingGet, appsettingSet
        if appsettingGet('obs_last_error', ''):
            appsettingSet('obs_last_error', '')
    except Exception:
        pass


def _run():
    global _ws, _restart_requested
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
            log.warning('websocket-client not installed — OBS control disabled')
            return

        url = f"ws://{cfg['host']}:{cfg['port']}"
        _set_state('connecting' if _state in ('disabled', 'connecting',
                                              'unsupported', 'auth_failed')
                   else 'reconnecting')
        started = time.monotonic()
        try:
            ws = websocket.create_connection(url, timeout=_RECV_TIMEOUT_S)
        except Exception as exc:
            # OBS not running is the ordinary case — keep this at INFO.
            log.info('OBS connect failed (%s); retry in %ss', exc, backoff)
            _sleep_backoff(backoff)
            backoff = _next_backoff(backoff)
            continue

        with _lock:
            _ws = ws
        parked = False
        try:
            _session_loop(ws, cfg)
        except _AuthFailed as exc:
            _set_state('auth_failed')
            _record_error('identify', exc)
            log.warning('OBS rejected the WebSocket password — check Broadcast settings')
            parked = True
        except _Unsupported as exc:
            _set_state('unsupported')
            _record_error('identify', exc)
            log.warning('OBS WebSocket unsupported: %s', exc)
            parked = True
        except Exception as exc:
            log.info('OBS session ended: %s', exc)
        finally:
            _close_socket()
            _fail_pending()
            with _cache_lock:
                _cache.update(_blank_cache())
            if not _stop.is_set() and not parked:
                _set_state('reconnecting')

        if parked:
            # Wrong password / wrong protocol: wait for new settings rather
            # than reconnecting on a loop.
            if not _wait_for_restart():
                return
            backoff = 2
            continue
        if time.monotonic() - started > _HEALTHY_RUN_S:
            backoff = 2                    # long healthy run: fast reconnect
        if not _stop.is_set() and not _restart_requested:
            _sleep_backoff(backoff)
            backoff = _next_backoff(backoff)
    _set_state('disabled')


class _AuthFailed(Exception):
    pass


class _Unsupported(Exception):
    pass


def _wait_for_restart():
    """Park until restart()/stop(). True = keep looping."""
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
    """One connected session: Hello -> Identify -> Identified -> prime -> pump."""
    import websocket

    _set_state('identifying')
    hello = _await_op(ws, 0, _HELLO_TIMEOUT_S)
    if hello is None:
        raise RuntimeError('no Hello within timeout')

    ident = {'rpcVersion': _RPC_VERSION, 'eventSubscriptions': EVENT_SUBS}
    auth = hello.get('authentication')
    if auth:
        # No password configured but OBS wants one: fail fast and clearly.
        ident['authentication'] = _auth_digest(
            cfg['password'], auth.get('salt', ''), auth.get('challenge', ''))
    ws.send(json.dumps({'op': 1, 'd': ident}))

    try:
        identified = _await_op(ws, 2, _HELLO_TIMEOUT_S)
    except websocket.WebSocketConnectionClosedException:
        identified = None
    if identified is None:
        # OBS closes the socket (code 4009) on a bad password. Classify
        # structurally — don't depend on the close code being surfaced.
        raise _AuthFailed('authentication failed or Identify was refused')

    negotiated = identified.get('negotiatedRpcVersion', _RPC_VERSION)
    if negotiated != _RPC_VERSION:
        raise _Unsupported(f'obs-websocket negotiated rpcVersion {negotiated}')

    with _cache_lock:
        _cache['ws_version'] = hello.get('obsWebSocketVersion', '')

    _prime(ws)
    _set_state('connected')
    _clear_error()
    log.info('OBS connected (obs-websocket %s)', hello.get('obsWebSocketVersion', '?'))

    while not _stop.is_set() and not _restart_requested:
        try:
            raw = ws.recv()
        except websocket.WebSocketTimeoutException:
            continue                       # routine: keeps ping/pong pumping
        if raw is None or raw == '':
            raise RuntimeError('socket closed by OBS')
        try:
            frame = json.loads(raw)
        except (ValueError, TypeError):
            continue
        _dispatch(frame)


def _await_op(ws, want_op, timeout):
    """Read frames until the wanted opcode arrives. Frames that show up in the
    meantime are dispatched normally (OBS can emit events mid-handshake)."""
    import websocket
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            raw = ws.recv()
        except websocket.WebSocketTimeoutException:
            continue
        if raw is None or raw == '':
            return None                    # closed before answering
        try:
            frame = json.loads(raw)
        except (ValueError, TypeError):
            continue
        if frame.get('op') == want_op:
            return frame.get('d') or {}
        _dispatch(frame)
    return None


def _prime(ws):
    """Fill the cache before flipping to CONNECTED.

    Sends the opening requests and drains their replies inline: request()
    refuses while state != connected, and the reader thread is the only one
    running at this point, so it must do its own correlation here."""
    wants = [('GetVersion', {}), ('GetSceneList', {}),
             ('GetSceneTransitionList', {}), ('GetRecordStatus', {}),
             ('GetStreamStatus', {}), ('GetStudioModeEnabled', {}),
             # Needed to build player scenes: canvas size for the browser
             # source, and which input kind this build calls a browser.
             ('GetVideoSettings', {}), ('GetInputKindList', {})]
    ids = {}
    for rt, data in wants:
        rid = str(next(_req_ids))
        ids[rid] = rt
        ws.send(json.dumps({'op': 6, 'd': {'requestType': rt,
                                           'requestId': rid,
                                           'requestData': data}}))

    import websocket
    deadline = time.monotonic() + _PRIME_TIMEOUT_S
    while ids and time.monotonic() < deadline:
        try:
            raw = ws.recv()
        except websocket.WebSocketTimeoutException:
            continue
        if raw is None or raw == '':
            raise RuntimeError('socket closed during priming')
        try:
            frame = json.loads(raw)
        except (ValueError, TypeError):
            continue
        d = frame.get('d') or {}
        rid = d.get('requestId')
        if frame.get('op') != 7 or rid not in ids:
            _dispatch(frame)
            continue
        rt = ids.pop(rid)
        status = d.get('requestStatus') or {}
        if not status.get('result'):
            # A missing optional request (older OBS) must not block the link.
            log.info('OBS priming request %s rejected: %s', rt, status.get('comment', ''))
            continue
        _apply_primed(rt, d.get('responseData') or {})


def _apply_primed(request_type, data):
    if request_type == 'GetVersion':
        with _cache_lock:
            _cache['obs_version'] = data.get('obsVersion', '')
            _cache['ws_version'] = data.get('obsWebSocketVersion',
                                            _cache.get('ws_version', ''))
    elif request_type == 'GetSceneList':
        _apply_scene_list(data)
    elif request_type == 'GetSceneTransitionList':
        with _cache_lock:
            _cache['transitions'] = [
                {'name': t.get('transitionName', ''),
                 'fixed': bool(t.get('transitionFixed'))}
                for t in (data.get('transitions') or [])]
            _cache['current_transition'] = data.get('currentSceneTransitionName', '')
    elif request_type == 'GetRecordStatus':
        with _cache_lock:
            _cache['recording'] = bool(data.get('outputActive'))
            _cache['record_timecode'] = data.get('outputTimecode', '')
    elif request_type == 'GetStreamStatus':
        with _cache_lock:
            _cache['streaming'] = bool(data.get('outputActive'))
            _cache['stream_timecode'] = data.get('outputTimecode', '')
    elif request_type == 'GetStudioModeEnabled':
        with _cache_lock:
            _cache['studio_mode'] = bool(data.get('studioModeEnabled'))
    elif request_type == 'GetVideoSettings':
        with _cache_lock:
            _cache['base_width'] = data.get('baseWidth') or 1920
            _cache['base_height'] = data.get('baseHeight') or 1080
    elif request_type == 'GetInputKindList':
        with _cache_lock:
            _cache['input_kinds'] = list(data.get('inputKinds') or [])


def _apply_scene_list(data):
    """OBS returns scenes in reverse UI order — sceneIndex 0 is the BOTTOM of
    the list. Sort descending so the dropdown reads like the OBS panel."""
    scenes = data.get('scenes') or []
    try:
        scenes = sorted(scenes, key=lambda s: s.get('sceneIndex', 0), reverse=True)
    except TypeError:
        pass
    names = [s.get('sceneName', '') for s in scenes if s.get('sceneName')]
    with _cache_lock:
        _cache['scenes'] = names
        current = data.get('currentProgramSceneName')
        if current:
            _cache['current_scene'] = current


def _dispatch(frame):
    op = frame.get('op')
    d = frame.get('d') or {}
    if op in (7, 9):                        # RequestResponse / batch response
        slot = _pending.get(d.get('requestId'))
        if slot is not None:
            slot['reply'] = frame
            slot['evt'].set()
        return
    if op == 5:
        _handle_event(d.get('eventType', ''), d.get('eventData') or {})


def _handle_event(event_type, data):
    """Cache updates only — never a request() call from the reader thread."""
    if event_type == 'CurrentProgramSceneChanged':
        with _cache_lock:
            _cache['current_scene'] = data.get('sceneName', '')
    elif event_type == 'SceneListChanged':
        _apply_scene_list({'scenes': data.get('scenes') or []})
    elif event_type == 'SceneNameChanged':
        old, new = data.get('oldSceneName', ''), data.get('sceneName', '')
        with _cache_lock:
            _cache['scenes'] = [new if s == old else s for s in _cache['scenes']]
            if _cache['current_scene'] == old:
                _cache['current_scene'] = new
    elif event_type == 'RecordStateChanged':
        with _cache_lock:
            _cache['recording'] = bool(data.get('outputActive'))
    elif event_type == 'StreamStateChanged':
        with _cache_lock:
            _cache['streaming'] = bool(data.get('outputActive'))
    elif event_type == 'CurrentSceneTransitionChanged':
        with _cache_lock:
            _cache['current_transition'] = data.get('transitionName', '')
    elif event_type == 'CurrentSceneTransitionDurationChanged':
        with _cache_lock:
            _cache['transition_ms'] = data.get('transitionDuration', 0) or 0
    elif event_type == 'StudioModeStateChanged':
        with _cache_lock:
            _cache['studio_mode'] = bool(data.get('studioModeEnabled'))
    elif event_type == 'ExitStarted':
        # OBS is closing: drop now so the reconnect loop starts cleanly
        # instead of waiting for the socket to time out.
        raise _ObsExiting()


class _ObsExiting(Exception):
    """OBS announced it is shutting down."""
