import logging
import threading

log = logging.getLogger(__name__)


def _cfg():
    from sql import appsettingGet
    return {
        'enabled':    appsettingGet('relay_enabled', '0'),
        'url':        appsettingGet('relay_url', ''),
        'secret':     appsettingGet('relay_secret', ''),
        'session_id': appsettingGet('relay_session_id', ''),
    }


def _active():
    cfg = _cfg()
    if cfg['enabled'] != '1' or not cfg['url'] or not cfg['session_id']:
        return None
    return cfg


def _exec_cfg():
    """Config resolved at EXECUTION time, not enqueue time. 'Generate code'
    can replace the relay session while a push waits in the queue; aimed at
    the dead session id, the push 404s and is dropped as permanent (the
    'library: 404' health-banner drop). Returns None when the relay was
    disabled after enqueue — skip the push rather than fail it."""
    return _active()


def _post(path, payload, cfg, timeout=5):
    import requests
    url = cfg['url'].rstrip('/') + path
    headers = {'X-Relay-Secret': cfg['secret'], 'Content-Type': 'application/json'}
    resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
    # The push queue's contract is "fn raises on failure" — without this, a
    # relay-side 4xx/5xx (e.g. disk full while writing a map) counted as a
    # SUCCESSFUL push and the payload was silently dropped.
    resp.raise_for_status()
    return resp


# ── Push queue ────────────────────────────────────────────────────────────────
# One background worker drains an ordered queue of push closures. Replaces the
# old fire-and-forget per-push threads, whose failures were logged and DROPPED —
# a sleeping/flaky relay silently lost map/token/roll/character updates.
#
# Coalescing: enqueueing with an existing key REPLACES that entry, so while the
# relay is unreachable only the LATEST map state / character payload per key is
# kept (dice rolls use unique keys and all queue).
#
# Failure handling: a 4xx from the relay is a permanent rejection — drop it
# immediately (retrying a 404/422 forever can't succeed). Network errors and
# 5xx retry with per-ENTRY backoff: the failed entry is stamped with a
# next-retry time and moved to the tail, so one doomed push can never block
# the healthy ones behind it (the old worker slept in the loop, wedging every
# queued token/HP/character push for minutes per doomed entry).
import itertools
import time as _time
from collections import OrderedDict

_queue      = OrderedDict()      # key -> [fn, attempts, next_retry_monotonic]
_queue_lock = threading.Lock()
_queue_evt  = threading.Event()
_worker     = None
_seq        = itertools.count()  # unique suffix for non-coalescing keys
_MAX_ATTEMPTS = 8                # ~2 minutes of retries before dropping


def _enqueue(key, fn):
    """Queue `fn` (which must RAISE on failure) under a coalescing key."""
    global _worker
    with _queue_lock:
        _queue[key] = [fn, 0, 0.0]
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_worker_run, daemon=True,
                                       name='relay-push')
            _worker.start()
    _queue_evt.set()


def _is_permanent(exc):
    """4xx = the relay understood and refused; retrying cannot help."""
    resp = getattr(exc, 'response', None)
    code = getattr(resp, 'status_code', None)
    return code is not None and 400 <= code < 500


def _record_push_drop(key, exc):
    """Persist the most recent dropped push so the DM health banner can show
    it — a drop is silent data loss toward the portal and worth surfacing."""
    try:
        from datetime import datetime, timezone
        from sql import appsettingSet
        ts = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
        appsettingSet('relay_push_last_drop', f'{ts}|{key}|{str(exc)[:120]}')
    except Exception:
        pass   # never let telemetry break the worker


def _worker_run():
    while True:
        _queue_evt.wait()
        now = _time.monotonic()
        with _queue_lock:
            if not _queue:
                _queue_evt.clear()
                continue
            key = entry = None
            soonest = None
            for k, e in _queue.items():
                if e[2] <= now:
                    key, entry = k, e
                    break
                soonest = e[2] if soonest is None else min(soonest, e[2])
        if entry is None:
            # everything is backing off — sleep until the earliest retry,
            # but wake early if a new push arrives
            _queue_evt.clear()
            _queue_evt.wait(timeout=max(0.05, (soonest or now) - now))
            _queue_evt.set()
            continue
        fn, attempts = entry[0], entry[1]
        try:
            fn()
            with _queue_lock:
                if _queue.get(key) is entry:   # not replaced by a newer payload
                    del _queue[key]
            # The relay answered — it has RECOVERED: clear the failure flag
            # immediately instead of letting the navbar badge age out.
            try:
                from sql import appsettingGet, appsettingSet
                if appsettingGet('relay_push_last_drop', ''):
                    appsettingSet('relay_push_last_drop', '')
            except Exception:
                pass
        except Exception as e:
            attempts += 1
            if _is_permanent(e) or attempts >= _MAX_ATTEMPTS:
                log.warning('relay push %r dropped (attempt %d, %s): %s',
                            key, attempts,
                            'rejected' if _is_permanent(e) else 'gave up', e)
                _record_push_drop(key, e)
                with _queue_lock:
                    if _queue.get(key) is entry:
                        del _queue[key]
            else:
                backoff = min(2.0 ** attempts, 30.0)
                entry[1] = attempts
                entry[2] = _time.monotonic() + backoff
                log.info('relay push %r failed (attempt %d, retry in %.0fs): %s',
                         key, attempts, backoff, e)
                with _queue_lock:
                    if _queue.get(key) is entry:
                        _queue.move_to_end(key)   # let healthy pushes proceed


# ── Public API ────────────────────────────────────────────────────────────────

def broadcast_roll(char_name, expression, label, dice, modifier, total, adv_mode='normal'):
    """POST /api/v1/session/{id}/push-roll — forward a local dice roll to the relay feed."""
    cfg = _active()
    if not cfg:
        return
    import json as _json
    breakdown = ', '.join(str(d) for d in dice)
    if modifier > 0:  breakdown += f'+{modifier}'
    elif modifier < 0: breakdown += str(modifier)
    roll_expr = expression
    if label: roll_expr += ' ' + label
    payload = {
        'player_name': char_name,
        'roll_expr':   roll_expr,
        'result':      total,
        'breakdown':   breakdown,
    }

    def _go():
        c = _exec_cfg()
        if not c:
            return
        _post(f'/api/v1/session/{c["session_id"]}/push-roll', payload, c)

    _enqueue(f'roll-{next(_seq)}', _go)   # unique key: every roll is delivered


def _downscale_image(raw, orig_ext, max_dim, quality=82):
    """Shrink image bytes before they're base64-embedded into a relay payload:
    downscale to `max_dim` on the long side and recompress (opaque -> JPEG,
    transparent -> PNG). Uses Pillow if installed; if Pillow is missing, the image
    is animated, or anything errors, the ORIGINAL bytes are returned unchanged so
    the relay keeps working. Returns (bytes, ext)."""
    try:
        import io
        from PIL import Image
        im = Image.open(io.BytesIO(raw))
        if getattr(im, 'is_animated', False):
            return raw, orig_ext          # don't flatten animated GIF/WebP
        if max_dim and max(im.size) > max_dim:
            im.thumbnail((max_dim, max_dim), Image.LANCZOS)
        # Decide JPEG vs PNG by ACTUAL transparency, not just an alpha channel:
        # many opaque PNGs (e.g. AI-generated maps) carry an unused alpha channel
        # and compress terribly as PNG. Only keep PNG if a pixel is really see-through.
        has_alpha = False
        if im.mode in ('RGBA', 'LA') or (im.mode == 'P' and 'transparency' in im.info):
            alpha = im.convert('RGBA').getchannel('A')
            has_alpha = alpha.getextrema()[0] < 255
        buf = io.BytesIO()
        if has_alpha:
            im.convert('RGBA').save(buf, format='PNG', optimize=True)
            out, ext = buf.getvalue(), 'png'
        else:
            im.convert('RGB').save(buf, format='JPEG', quality=quality, optimize=True)
            out, ext = buf.getvalue(), 'jpg'
        if len(out) < len(raw):           # only adopt it if it actually shrank
            return out, ext
    except Exception:
        pass
    return raw, orig_ext


_MAP_VIDEO_EXTS = ('mp4', 'webm', 'ogv')
_MAP_VIDEO_CAP  = 30 * 1024 * 1024   # raw bytes; base64 adds ~33% on top
_MAP_BG_CACHE   = {'key': None, 'val': (None, None, None)}   # (filename, mtime) → result


def _battlemap_data(filename):
    """Return (base64_data, ext, sha) for a battlemap background, or (None,)*3.

    Still images are downscaled/recompressed to keep the relay payload small;
    video backgrounds are embedded AS-IS up to _MAP_VIDEO_CAP (an oversize video
    falls back to the URL — invisible to remote players — with a warning).
    `sha` is sha256[:32] of the bytes the relay would store, matching the
    relay's on-disk filename so pushes can say "you already have this file"
    instead of re-uploading it. Cached per (filename, mtime): map state pushes
    fire on every token nudge and must not re-encode a video each time."""
    if not filename:
        return None, None, None
    import base64, hashlib, os
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    if ext not in ('png', 'jpg', 'jpeg', 'gif', 'webp') + _MAP_VIDEO_EXTS:
        return None, None, None
    try:
        from flask import current_app
        path = os.path.join(current_app.root_path, 'static', 'uploads', 'battlemaps', filename)
    except RuntimeError:
        return None, None, None
    if not os.path.exists(path):
        return None, None, None
    try:
        key = (filename, os.path.getmtime(path))
        if _MAP_BG_CACHE['key'] == key:
            return _MAP_BG_CACHE['val']
        if ext in _MAP_VIDEO_EXTS:
            size = os.path.getsize(path)
            if size > _MAP_VIDEO_CAP:
                log.warning('battlemap video %s is %.1f MB — over the %d MB relay embed '
                            'cap, remote players will not see it',
                            filename, size / 1048576, _MAP_VIDEO_CAP // 1048576)
                return None, None, None
            with open(path, 'rb') as f:
                out_bytes, out_ext = f.read(), ext
        else:
            with open(path, 'rb') as f:
                raw = f.read()
            out_bytes, out_ext = _downscale_image(raw, ext, max_dim=1920, quality=82)
        val = (base64.b64encode(out_bytes).decode('ascii'), out_ext,
               hashlib.sha256(out_bytes).hexdigest()[:32])
        _MAP_BG_CACHE['key'], _MAP_BG_CACHE['val'] = key, val
        return val
    except Exception:
        return None, None, None


# _push_map_state fires from ~13 route call sites (every token nudge, effect
# tweak, bg change). Two cheap guards keep that from flooding the relay:
#   hash-skip — identical payloads (vs the last SUCCESSFUL push) are dropped;
#   debounce  — pushes wait 250ms and reset on each new call, so a drag burst
#               collapses into one push (coalescing in the queue handles the rest).
_MAP_DEBOUNCE_S    = 0.25
_last_map_hash     = {'v': None}


def reset_map_push_cache():
    """Forget the last successfully pushed map state so the NEXT
    broadcast_map_update sends unconditionally — used by the receiver's
    auto-repush when the relay's stored map went stale (dropped push,
    relay restart) with no local change to break the hash."""
    _last_map_hash['v'] = None
_map_debounce      = {'timer': None}
_map_debounce_lock = threading.Lock()


def _debounced_map_enqueue(fn):
    with _map_debounce_lock:
        if _map_debounce['timer'] is not None:
            _map_debounce['timer'].cancel()
        t = threading.Timer(_MAP_DEBOUNCE_S, lambda: _enqueue('map-state', fn))
        t.daemon = True
        _map_debounce['timer'] = t
        t.start()


def broadcast_map_update(bg_url, grid_cols, grid_rows, tokens, effects=None,
                         movement_scale=1.0, bg_filename=None):
    """POST /api/v1/session/push  body: { session_id, map: { url, ... } }

    When bg_filename names a still image, its bytes are embedded as base64 so a
    remote relay (which cannot reach this LAN server) can serve the map itself."""
    cfg = _active()
    if not cfg:
        return
    payload = {
        'session_id': cfg['session_id'],
        'map': {
            'url':       bg_url,
            'grid_cols': grid_cols,
            'grid_rows': grid_rows,
            'tokens':    tokens,
            'effects':   effects or [],
            'movement_scale': movement_scale,
        },
    }
    # Two-step background transfer: the normal push carries only a content sha
    # (tiny — token moves on a video map must not re-upload megabytes each
    # nudge). If the relay doesn't have that file it answers need_image and the
    # heavy payload with the actual base64 bytes is sent once.
    bg_data, bg_ext, bg_sha = _battlemap_data(bg_filename)
    heavy = None
    if bg_data:
        payload['map']['image_sha'] = bg_sha
        payload['map']['image_ext'] = bg_ext
        if bg_ext in _MAP_VIDEO_EXTS:
            mime = 'video/' + ('ogg' if bg_ext == 'ogv' else bg_ext)
        else:
            mime = 'image/' + ('jpeg' if bg_ext == 'jpg' else bg_ext)
        # data: URL doubles as the fallback the portal can render directly if
        # the relay cannot write the file (e.g. its disk is full).
        heavy = dict(payload, map=dict(payload['map']))
        heavy['map']['url']        = f'data:{mime};base64,{bg_data}'
        heavy['map']['image_data'] = bg_data

    import hashlib
    import json as _json
    digest = hashlib.sha1(
        _json.dumps(heavy or payload, sort_keys=True).encode()).hexdigest()
    if digest == _last_map_hash['v']:
        return   # nothing changed since the last successful push

    def _go():
        c = _exec_cfg()
        if not c:
            return
        payload['session_id'] = c['session_id']
        resp = _post('/api/v1/session/push', payload, c, timeout=20)
        if heavy is not None:
            heavy['session_id'] = c['session_id']
            try:
                need = bool(resp.json().get('need_image'))
            except Exception:
                need = False
            if need:
                # Generous window: the heavy payload can carry a video on a
                # slow home uplink. Only happens when the relay lacks the file.
                _post('/api/v1/session/push', heavy, c, timeout=120)
        _last_map_hash['v'] = digest   # only remember payloads that landed

    _debounced_map_enqueue(_go)   # queue coalesces on 'map-state'; latest wins


def broadcast_led(led_pattern_json):
    """POST /api/v1/session/{id}/led — mirror the LAN LED push to remote
    players' home Pis (via the relay portal). Takes the same JSON string
    remoteSend() takes: {"patterns": [...]}. Always the LAN variant (no
    outPinID/brightness) — each remote Pi applies its own strip config."""
    cfg = _active()
    if not cfg:
        return
    import json as _json
    try:
        patterns = _json.loads(led_pattern_json).get('patterns')
    except (ValueError, TypeError, AttributeError):
        log.warning('broadcast_led: bad LED pattern JSON')
        return
    if not patterns:
        return
    payload = {'patterns': patterns}

    def _go():
        c = _exec_cfg()
        if not c:
            return
        _post(f'/api/v1/session/{c["session_id"]}/led', payload, c)

    _enqueue('led-state', _go)   # coalesce: only the latest lighting state matters


def broadcast_now_playing(song_id, stream_active):
    """POST /api/v1/session/{id}/now-playing — current music track (name +
    thumbnail) and whether a live audio stream is up, for the portal's music
    widget. song_id None/0 + stream_active False means playback stopped."""
    cfg = _active()
    if not cfg:
        return
    payload = {'song_id': None, 'name': None, 'thumbnail': None,
               'stream_active': bool(stream_active)}
    if song_id:
        try:
            import sqlite3
            from sql import database as _dbpath
            conn = sqlite3.connect(_dbpath)
            c = conn.cursor()
            # Same name/thumbnail resolution as sql.get_now_playing's music half
            c.execute("SELECT COALESCE(NULLIF(m.displayName,''), m.song), md.thumbnail "
                      "FROM tblMusic m LEFT JOIN tblMediaMetadata md "
                      "ON md.media_type='music' AND md.media_id=m.song_ID "
                      "WHERE m.song_ID = ?", (song_id,))
            row = c.fetchone()
            c.close()
            conn.close()
            if row:
                payload.update(song_id=int(song_id), name=row[0], thumbnail=row[1])
        except Exception:
            log.warning('broadcast_now_playing: metadata lookup failed')

    def _go():
        c = _exec_cfg()
        if not c:
            return
        _post(f'/api/v1/session/{c["session_id"]}/now-playing', payload, c)

    _enqueue('now-playing', _go)   # coalesce: only the latest track matters


def broadcast_wled(wled_rows):
    """POST /api/v1/session/{id}/wled — mirror the scene's WLED lighting to
    remote players' home WLED controllers (via the relay portal).

    Takes the tblwledPattern rows for the scene (or None/empty → lights off).
    Effect/palette IDs are resolved to NAMES here — indices vary by WLED
    firmware version, so each player's browser re-resolves names against its
    own device. server_ID targets a DM-LAN device and is dropped."""
    cfg = _active()
    if not cfg:
        return
    import json as _json

    patterns = []
    if wled_rows:
        from models.wledPattern import tbleffect as ef
        from models.wledPattern import tblpallette as pt

        def _color(raw):
            try:
                return _json.loads(raw)
            except (ValueError, TypeError):
                return [0, 0, 0]

        for row in wled_rows:
            effect = ef.query.filter(ef.ef_ID == row.effect).first()
            if effect is None:
                continue   # can't name the effect — the browser couldn't resolve it
            pallette = pt.query.filter(pt.pa_ID == row.pallette).first()
            # WLED effect names carry metadata after '@' (e.g. "Fireworks@!,!")
            name = effect.effectName.split('@')[0] if '@' in effect.effectName \
                else effect.effectName
            patterns.append({
                'effect':     name,
                'palette':    pallette.palletteName if pallette else None,
                # Firmware indices too (ef_ID/pa_ID are 1-based over the DM
                # device's 0-based arrays): the relay's MQTT bridge needs
                # numeric IDs — WLED's JSON API can't resolve names, and the
                # relay can't reach a player's device to build a catalog.
                'effect_id':  effect.ef_ID - 1,
                'palette_id': (pallette.pa_ID - 1) if pallette else None,
                'colors':     [_color(row.color1), _color(row.color2), _color(row.color3)],
                'speed':      row.speed,
                'brightness': row.brightness,
            })

    payload = {'off': True} if not patterns else {'patterns': patterns}

    def _go():
        c = _exec_cfg()
        if not c:
            return
        _post(f'/api/v1/session/{c["session_id"]}/wled', payload, c)

    _enqueue('wled-state', _go)   # coalesce: only the latest lighting state matters


def broadcast_token_move(token_id, x_pct, y_pct,
                         label='', token_type='player', character_id=None):
    """POST /api/v1/token/move  body: { token_id, x_pct, y_pct, session_id?, label?, ... }"""
    cfg = _active()
    if not cfg:
        return
    body = {
        'token_id':   str(token_id),
        'x_pct':      x_pct,
        'y_pct':      y_pct,
        'session_id': cfg['session_id'],
        'label':      label,
        'token_type': token_type,
    }
    if character_id is not None:
        body['character_id'] = str(character_id)

    def _go():
        c = _exec_cfg()
        if not c:
            return
        body['session_id'] = c['session_id']
        _post('/api/v1/token/move', body, c)

    _enqueue(f'token-move-{token_id}', _go)   # coalesce per token


def broadcast_token_health(token_id, hp_current, hp_max):
    """POST /api/v1/token/health  body: { token_id, hp_current, hp_max, session_id }"""
    cfg = _active()
    if not cfg:
        return
    body = {'token_id': str(token_id), 'hp_current': hp_current, 'hp_max': hp_max,
            'session_id': cfg['session_id']}

    def _go():
        c = _exec_cfg()
        if not c:
            return
        body['session_id'] = c['session_id']
        _post('/api/v1/token/health', body, c)

    _enqueue(f'token-health-{token_id}', _go)   # coalesce per token


def broadcast_condition_update(conditions, token_id=None, player_name=None):
    """POST /api/v1/session/{id}/condition-update — push condition list change via SSE."""
    cfg = _active()
    if not cfg:
        return
    body = {'conditions': conditions}
    if token_id is not None:
        body['token_id'] = str(token_id)
    if player_name is not None:
        body['player_name'] = player_name

    def _go():
        c = _exec_cfg()
        if not c:
            return
        _post(f'/api/v1/session/{c["session_id"]}/condition-update', body, c)

    _enqueue(f'condition-{token_id or player_name}', _go)   # coalesce per target


def _portrait_data(char):
    """Return (ext, base64_data) for the character portrait, or (None, None).
    The portrait is downscaled/recompressed first to shrink the relay payload."""
    if not char.portrait_path:
        return None, None
    import base64, os
    try:
        from flask import current_app
        path = os.path.join(current_app.root_path, 'static', 'uploads', 'portraits', char.portrait_path)
    except RuntimeError:
        return None, None
    if not os.path.exists(path):
        return None, None
    try:
        ext = char.portrait_path.rsplit('.', 1)[-1].lower() if '.' in char.portrait_path else 'png'
        with open(path, 'rb') as f:
            raw = f.read()
        data, new_ext = _downscale_image(raw, ext, max_dim=384, quality=82)
        return new_ext, base64.b64encode(data).decode('ascii')
    except Exception:
        return None, None


def _char_to_payload(char):
    """Build the character dict expected by POST /api/v1/session/{id}/characters."""
    import json as _json
    sheet = {
        'name':               char.name,
        'class':              char.char_class,
        'subclass':           getattr(char, 'subclass', '') or '',
        'race':               char.race,
        'level':              char.level,
        'background':         char.background,
        'ac':                 char.ac,
        'speed':              char.speed,
        'initiative_bonus':   char.initiative_bonus,
        'passive_perception': char.passive_perception,
        'gold':               char.gold,
        'silver':             char.silver,
        'copper':             char.copper,
        'str': char.str_val, 'dex': char.dex_val,
        'con': char.con_val, 'int': char.int_val,
        'wis': char.wis_val, 'cha': char.cha_val,
        'skills': [
            {'name': s.skill_name, 'bonus': s.bonus, 'proficient': bool(s.proficient)}
            for s in sorted(char.skills, key=lambda x: x.order_by)
        ],
        'resources': [
            {'name': r.resource_name, 'current': r.current_val, 'max': r.max_val}
            for r in sorted(char.resources, key=lambda x: x.order_by)
        ],
        'inventory': [
            {'name': i.item_name, 'qty': i.quantity, 'weight': i.weight or '',
             'notes': i.notes or '', 'equipped': bool(i.equipped)}
            for i in sorted(char.inventory, key=lambda x: x.order_by)
        ],
        'feats': [
            {'name': f.feat_name, 'description': f.description}
            for f in sorted(char.feats, key=lambda x: x.order_by)
        ],
        'conditions': [c.condition_name for c in char.conditions],
        'weapons': [
            {
                'name':                  w.weapon_name,
                'category':              w.weapon_category  or '',
                'range':                 w.weapon_range     or '',
                'damage_dice':           w.damage_dice      or '',
                'damage_type':           w.damage_type      or '',
                'two_handed_damage_dice': w.two_handed_damage_dice or '',
                'two_handed_damage_type': w.two_handed_damage_type or '',
                'range_normal':          w.range_normal     or 0,
                'range_long':            w.range_long       or 0,
                'properties':            w.properties       or '',
                'damage_bonus':          w.damage_bonus     or 0,
                'attack_bonus':          w.attack_bonus     or 0,
                'notes':                 w.notes            or '',
                'equipped':              bool(w.equipped),
            }
            for w in sorted(char.weapons, key=lambda x: x.order_by)
        ],
        'armor': [
            {
                'name':          a.armor_name,
                'category':      a.armor_category   or '',
                'ac_base':       a.armor_class_base,
                'ac_bonus':      a.ac_bonus          or 0,
                'dex_bonus':     bool(a.dex_bonus),
                'max_dex_bonus': a.max_dex_bonus,
                'notes':         a.notes             or '',
                'equipped':      bool(a.equipped),
                'is_shield':     a.armor_category == 'Shield',
            }
            for a in sorted(char.armor, key=lambda x: x.order_by)
        ],
        'spells': [
            {
                'name':         cs.spell_name,
                'level':        cs.spell_level,
                'school':       cs.school        or '',
                'casting_time': (cs.lib_spell.casting_time if cs.lib_spell else '') or '',
                'range':        (cs.lib_spell.range_text   if cs.lib_spell else '') or '',
                'components':   (cs.lib_spell.components   if cs.lib_spell else '') or '',
                'duration':     (cs.lib_spell.duration     if cs.lib_spell else '') or '',
                'concentration': bool(cs.lib_spell.concentration if cs.lib_spell else False),
                'ritual':       bool(cs.lib_spell.ritual   if cs.lib_spell else False),
                'classes':      (cs.lib_spell.classes_text if cs.lib_spell else '') or '',
                'description':  (cs.lib_spell.description  if cs.lib_spell else '') or '',
                'damage_dice':  (cs.lib_spell.damage_dice  if cs.lib_spell else '') or '',
                'damage_type':  (cs.lib_spell.damage_type  if cs.lib_spell else '') or '',
                'prepared':     bool(cs.prepared),
                'notes':        cs.notes         or '',
            }
            for cs in sorted(char.spells, key=lambda x: (x.spell_level, x.order_by))
        ],
        'notes': [
            {'text': n.note_text, 'created_at': n.created_at}
            for n in sorted(char.notes, key=lambda x: x.created_at)
        ],
    }
    user = char.user
    portrait_ext, portrait_b64 = _portrait_data(char)
    return {
        'player_name':     char.name,
        'username':        user.username      if user else '',
        'display_name':    user.display_name  if user else char.name,
        'password_hash':   user.password_hash if user else '',
        'portrait_url':    '',
        'portrait_data':   portrait_b64 or '',
        'portrait_ext':    portrait_ext or '',
        'sheet_json':      _json.dumps(sheet),
        'hp_current':      char.hp_current,
        'hp_max':          char.hp_max,
    }


def push_all_characters():
    """Push the active session's COMPLETE party to the relay.

    Calls POST /api/v1/session/{session_id}/characters with GM secret and
    replace=True: the relay upserts these and REMOVES any character in the
    relay session that isn't in this list — so activating a different local
    session (while keeping the same relay session/join code) can't leave
    players seeing characters from the previous session. An empty party is
    pushed too, for the same reason: it clears the relay's set.
    """
    cfg = _active()
    if not cfg:
        return

    from models.ttrpg import tblSessions
    sess = tblSessions.query.filter_by(status='active').first()
    if not sess:
        log.info('push_all_characters: no active session')
        return

    characters = []
    for sp in sess.party:
        char = sp.character
        if char:
            characters.append(_char_to_payload(char))

    payload = {'characters': characters, 'replace': True}

    def _go():
        c = _exec_cfg()
        if not c:
            return
        _post(f'/api/v1/session/{c["session_id"]}/characters', payload, c)
        log.info('push_all_characters: pushed %d characters (authoritative)',
                 len(characters))

    _enqueue('all-characters', _go)   # coalesce: latest full party wins


def _in_active_session(char):
    """True only if `char` is a party member of the currently active session.

    Gates single-character relay pushes so edits to characters outside the
    live session never leak to remote players."""
    if char is None:
        return False
    from models.ttrpg import tblSessions, tblSessionParty
    sess = tblSessions.query.filter_by(status='active').first()
    if not sess:
        return False
    return (tblSessionParty.query
            .filter_by(session_id=sess.session_id, character_id=char.character_id)
            .first() is not None)


def push_character(char):
    """Push a single character update to the relay (e.g. after HP change or sheet edit)."""
    cfg = _active()
    if not cfg:
        return
    if not _in_active_session(char):
        return
    payload = {'characters': [_char_to_payload(char)]}

    def _go():
        c = _exec_cfg()
        if not c:
            return
        _post(f'/api/v1/session/{c["session_id"]}/characters', payload, c)

    _enqueue(f'character-{char.character_id}', _go)   # coalesce per character


def push_character_and_broadcast(char):
    """Push a character update then trigger a sheet-updated SSE event on the relay portal."""
    cfg = _active()
    if not cfg:
        return
    if not _in_active_session(char):
        return
    payload = {'characters': [_char_to_payload(char)]}
    player_name = char.name

    def _go():
        c = _exec_cfg()
        if not c:
            return
        _post(f'/api/v1/session/{c["session_id"]}/characters', payload, c)
        _post(f'/api/v1/session/{c["session_id"]}/character-sheet-broadcast',
              {'player_name': player_name}, c)

    _enqueue(f'character-bcast-{char.character_id}', _go)   # coalesce per character


def push_library():
    """Push all D&D library tables to relay so portal can search them during character edit."""
    cfg = _active()
    if not cfg:
        return

    import json as _json
    from models.ttrpg import (tblSpellsLibrary, tblFeatsLibrary, tblWeaponsLibrary,
                               tblArmorLibrary, tblEquipmentLibrary, tblSkillsLibrary,
                               tblRacesLibrary, tblClassesLibrary, tblConditionsLibrary,
                               tblMagicItemsLibrary, tblFeaturesLibrary,
                               tblClassLevelsLibrary, tblSubclassesLibrary,
                               tblTraitsLibrary, tblWeaponPropertiesLibrary, tblRulesLibrary)

    def _loads(s):
        try:
            return _json.loads(s or '{}')
        except Exception:
            return {}

    payload = {
        'spells': [
            {'name': s.name, 'level': s.level, 'school': s.school or '',
             'casting_time': s.casting_time or '', 'range': s.range_text or '',
             'components': s.components or '', 'duration': s.duration or '',
             'concentration': bool(s.concentration), 'ritual': bool(s.ritual),
             'description': s.description or '', 'classes': s.classes_text or '',
             'damage_dice': s.damage_dice or '', 'damage_type': s.damage_type or ''}
            for s in tblSpellsLibrary.query.order_by(
                tblSpellsLibrary.level, tblSpellsLibrary.name).all()
        ],
        'feats': [
            {'name': f.name, 'prerequisites': f.prerequisites or '',
             'description': f.description or ''}
            for f in tblFeatsLibrary.query.order_by(tblFeatsLibrary.name).all()
        ],
        'weapons': [
            {'name': w.name, 'category': w.weapon_category or '',
             'range': w.weapon_range or '', 'damage_dice': w.damage_dice or '',
             'damage_type': w.damage_type or '',
             'two_handed_damage_dice': w.two_handed_damage_dice or '',
             'properties': w.properties or '', 'mastery': w.mastery or '',
             'notes': w.notes or ''}
            for w in tblWeaponsLibrary.query.order_by(tblWeaponsLibrary.name).all()
        ],
        'armor': [
            {'name': a.name, 'category': a.armor_category or '',
             'ac_base': a.armor_class_base, 'dex_bonus': bool(a.dex_bonus),
             'max_dex_bonus': a.max_dex_bonus, 'str_minimum': a.str_minimum,
             'stealth_disadvantage': bool(a.stealth_disadvantage),
             'notes': a.notes or ''}
            for a in tblArmorLibrary.query.order_by(tblArmorLibrary.name).all()
        ],
        'equipment': [
            {'name': e.name, 'category': e.category or '',
             'subcategory': e.subcategory or '', 'weight': e.weight,
             'cost': e.cost or '', 'description': e.description or ''}
            for e in tblEquipmentLibrary.query.order_by(tblEquipmentLibrary.name).all()
        ],
        'skills': [
            {'name': sk.name, 'ability': sk.ability_score or '',
             'description': sk.description or ''}
            for sk in tblSkillsLibrary.query.order_by(tblSkillsLibrary.name).all()
        ],
        'races': [
            {'name': r.name, 'speed': r.speed, 'size': r.size or '',
             'ability_bonuses': r.ability_bonuses or '', 'traits': r.traits_text or ''}
            for r in tblRacesLibrary.query.order_by(tblRacesLibrary.name).all()
        ],
        'classes': [
            {'name': c.name, 'hit_die': c.hit_die,
             'saving_throws': c.saving_throws or '',
             'spellcasting_ability': c.spellcasting_ability or '',
             'description': c.description or ''}
            for c in tblClassesLibrary.query.order_by(tblClassesLibrary.name).all()
        ],
        'conditions': [
            {'name': c.name, 'description': c.description or ''}
            for c in tblConditionsLibrary.query.order_by(tblConditionsLibrary.name).all()
        ],
        'magic_items': [
            {'name': m.name, 'category': m.category or '', 'rarity': m.rarity or '',
             'attunement': bool(m.attunement), 'description': m.description or ''}
            for m in tblMagicItemsLibrary.query.order_by(tblMagicItemsLibrary.name).all()
        ],
        'features': [
            {'name': f.name, 'class': f.class_name or '', 'subclass': f.subclass_name or '',
             'level': f.level or 0, 'description': f.description or ''}
            for f in tblFeaturesLibrary.query.order_by(
                tblFeaturesLibrary.class_name, tblFeaturesLibrary.level,
                tblFeaturesLibrary.name).all()
        ],
        'class_levels': [
            {'class': cl.class_name, 'level': cl.level, 'prof_bonus': cl.prof_bonus,
             'features': cl.features_text or '', 'cantrips_known': cl.cantrips_known or 0,
             'spells_known': cl.spells_known or 0,
             'spell_slots': _loads(cl.spell_slots_json),
             'class_specific': _loads(cl.class_specific_json)}
            for cl in tblClassLevelsLibrary.query.order_by(
                tblClassLevelsLibrary.class_name, tblClassLevelsLibrary.level).all()
        ],
        'subclasses': [
            {'name': s.name, 'class': s.class_name or '', 'flavor': s.flavor or '',
             'description': s.description or ''}
            for s in tblSubclassesLibrary.query.order_by(tblSubclassesLibrary.name).all()
        ],
        'traits': [
            {'name': t.name, 'races': t.races_text or '', 'description': t.description or ''}
            for t in tblTraitsLibrary.query.order_by(tblTraitsLibrary.name).all()
        ],
        'weapon_properties': [
            {'name': w.name, 'description': w.description or ''}
            for w in tblWeaponPropertiesLibrary.query.order_by(
                tblWeaponPropertiesLibrary.name).all()
        ],
        'rules': [
            {'name': r.name, 'parent': r.parent or '', 'description': r.description or ''}
            for r in tblRulesLibrary.query.order_by(
                tblRulesLibrary.parent, tblRulesLibrary.name).all()
        ],
    }

    def _go():
        c = _exec_cfg()
        if not c:
            return
        _post(f'/api/v1/session/{c["session_id"]}/library', payload, c)
        log.info('push_library: pushed library data to relay')

    _enqueue('library', _go)   # coalesce: latest library snapshot wins


def get_relay_rolls(since_id=0):
    """GET /api/v1/session/{id}/rolls — fetch relay roll log entries newer than since_id."""
    cfg = _active()
    if not cfg:
        return []
    try:
        import requests
        url = cfg['url'].rstrip('/') + f'/api/v1/session/{cfg["session_id"]}/rolls'
        resp = requests.get(url, params={'since_id': since_id},
                            headers={'X-Relay-Secret': cfg['secret']}, timeout=5)
        if resp.ok:
            return resp.json().get('rolls', [])
    except Exception as e:
        log.warning('get_relay_rolls failed: %s', e)
    return []


def get_presence():
    """GET /api/v1/session/{id}/presence — {player_name: seconds_since_last_seen}."""
    cfg = _active()
    if not cfg:
        return {}
    try:
        import requests
        url = cfg['url'].rstrip('/') + f'/api/v1/session/{cfg["session_id"]}/presence'
        resp = requests.get(url, headers={'X-Relay-Secret': cfg['secret']}, timeout=5)
        if resp.ok:
            return resp.json().get('presence', {})
    except Exception as e:
        log.warning('get_presence failed: %s', e)
    return {}


def push_session_users():
    """POST /session/{id}/users — push all active user accounts so anyone at
    the table can log into the portal BEFORE a character is assigned to them
    (spectator until the GM hands them a sheet)."""
    cfg = _active()
    if not cfg:
        return
    from models.user import tblUsers
    users = [{'username': u.username,
              'display_name': u.display_name,
              'password_hash': u.password_hash or ''}
             for u in tblUsers.query.filter_by(active=1).all()]
    if not users:
        return
    payload = {'users': users}

    def _go():
        c = _exec_cfg()
        if not c:
            return
        _post(f'/api/v1/session/{c["session_id"]}/users', payload, c)
        log.info('push_session_users: pushed %d users', len(users))

    _enqueue('session-users', _go)   # coalesce: latest user list wins


def remove_character(player_name):
    """DELETE /session/{id}/characters/{name} — drop a character that left the
    party. The relay broadcasts character_removed to connected portals, so the
    player's view updates without a re-login."""
    cfg = _active()
    if not cfg:
        return
    from urllib.parse import quote

    def _go():
        import requests
        c = _exec_cfg()
        if not c:
            return
        url = (c['url'].rstrip('/')
               + f'/api/v1/session/{c["session_id"]}/characters/'
               + quote(player_name, safe=''))
        resp = requests.delete(url, headers={'X-Relay-Secret': c['secret']}, timeout=5)
        # 404 = already gone on the relay; success as far as we're concerned
        # (retrying a delete of nothing would wedge the queue pointlessly).
        if resp.status_code not in (200, 404):
            resp.raise_for_status()

    _enqueue(f'char-del-{player_name}', _go)


def find_token_id(entity_type, entity_id):
    """Return the battlemap token_id for an entity on the active map, or None."""
    from models.ttrpg import tblSessions, tblBattleMaps, tblBattleMapTokens
    sess = tblSessions.query.filter_by(status='active').first()
    if not sess:
        return None
    bm = tblBattleMaps.query.filter_by(
        session_id=sess.session_id, is_active=1).first()
    if not bm:
        return None
    t = tblBattleMapTokens.query.filter_by(
        map_id=bm.map_id, entity_type=entity_type, entity_id=entity_id).first()
    return t.token_id if t else None
