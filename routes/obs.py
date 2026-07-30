"""OBS Studio control — the DM's Broadcast page and the go-live API.

Click a party member (here or on the battle map sidebar) and OBS cuts its
PROGRAM scene to that player's camera. Studio mode is deliberately not used:
this table cuts straight to program.

Everything talks to obs_ws, which holds a persistent socket — so a call here
either answers immediately or fails fast on an in-memory `connected()` check.
No queueing: the DM needs to know whether the cut happened.
"""
import logging
import re
import secrets
import string
import threading
from datetime import datetime

from flask import (Blueprint, render_template, redirect, url_for, abort,
                   request, flash, jsonify, current_app)
from flask_login import login_required, current_user

from extensions import db
from models.ttrpg import tblObsSceneMap, tblSessions, tblCharacters
from models.scenes import tblscenes
from routes.auth import dm_required
from sql import appsettingGet, appsettingSet

log = logging.getLogger(__name__)

obs_bp = Blueprint('obs_bp', __name__, url_prefix='/ttrpg/obs')

_TRANSITION_MS_MIN = 0
_TRANSITION_MS_MAX = 20000
_STREAM_ID_LEN = 24
_MAX_FEED_URL = 500

# Auto-return timer: after cutting to a player we drift back to the group
# shot so a session never gets stranded on someone who stopped talking.
# Server-side on purpose — it must fire whether or not a browser is open.
_return_timer = None
_return_lock = threading.Lock()


# ── helpers ───────────────────────────────────────────────────────────────────

def _obs_cfg():
    import obs_ws
    # appsettingGet's default only fires when the row is ABSENT, so an empty
    # stored value has to fall back here as well or the form shows blanks.
    return {
        'enabled':       appsettingGet('obs_enabled', '0') or '0',
        'host':          (appsettingGet('obs_host', '') or '').strip() or obs_ws.DEFAULT_HOST,
        'port':          (appsettingGet('obs_port', '') or '').strip() or str(obs_ws.DEFAULT_PORT),
        'has_password':  bool(appsettingGet('obs_password', '')),
        'transition':    appsettingGet('obs_transition', ''),
        'transition_ms': (appsettingGet('obs_transition_ms', '') or '').strip() or '300',
        'group_scene':   _special_scene('group'),
        'auto_return_s': (appsettingGet('obs_auto_return_s', '') or '').strip() or '0',
        'scene_link':    appsettingGet('obs_scene_link', '0') or '0',
        'has_vdo_password': bool(appsettingGet('obs_vdo_password', '')),
        # set by app.py's boot guard when a start crashed during OBS bring-up
        'boot_tripped':  appsettingGet('obs_boot_tripped', ''),
        'last_error':    appsettingGet('obs_last_error', ''),
    }


def _active_party():
    """Party of the ACTIVE session — the people who could be on camera now.
    Mirrors how the battle map builds its sidebar list."""
    sess = tblSessions.query.filter_by(status='active').first()
    if not sess:
        return []
    return [sp.character for sp in sess.party if sp.character]


def _scene_map():
    """{character_id: scene_name} for player rows."""
    return {row.entity_id: row.scene_name
            for row in tblObsSceneMap.query.filter_by(entity_type='player').all()}


def _now():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _special_scene(key):
    row = tblObsSceneMap.query.filter_by(entity_type='special', entity_id=0,
                                         entity_key=key).first()
    return row.scene_name if row else ''


def _presence():
    """{character_name: seconds_since_seen} from the relay, or {} when the
    relay is off. Only tells us about REMOTE players — someone sitting at the
    table with no portal login is simply unknown, never 'offline'."""
    try:
        import relay_broadcaster
        return relay_broadcaster.get_presence() or {}
    except Exception:
        return {}


def _feed_state(char, presence):
    """How ready is this player to be cut to?

    'live'    — has a feed and the relay saw them recently
    'ready'   — has a feed, presence unknown (LAN player, or relay off)
    'stale'   — has a feed but the relay says they dropped
    'nofeed'  — nothing to show
    """
    if not char.has_feed():
        return 'nofeed'
    secs = presence.get(char.name)
    if secs is None:
        return 'ready'
    return 'live' if secs < 90 else 'stale'


def _mapping_rows(party, snap):
    """Party + their mapped scene, flagging scenes that no longer exist in OBS
    (a rename or delete on the OBS side orphans the mapping) and how ready
    each player's feed is. Ordered by the rotation the Next/Prev keys walk."""
    mapped = _scene_map()
    order = _rotation_order()
    known = set(snap.get('scenes') or [])
    presence = _presence()
    rows = []
    for char in party:
        scene = mapped.get(char.character_id, '')
        rows.append({
            'character_id': char.character_id,
            'name': char.name,
            'scene': scene,
            'missing': bool(scene) and bool(known) and scene not in known,
            'live': bool(scene) and scene == snap.get('current_scene'),
            'feed': _feed_state(char, presence),
            'has_custom_url': bool(char.video_feed_url),
            'pos': order.index(char.character_id) + 1 if char.character_id in order else 0,
        })
    rows.sort(key=lambda r: (r['pos'] == 0, r['pos'], r['name'].lower()))
    return rows


def _rotation_order():
    """Character ids in camera-rotation order — what Next/Prev and the number
    keys walk. Only mapped players are in it: cutting to someone with no scene
    would just error. tblObsSceneMap.sort_order is rig config, which is
    exactly what a camera rotation is, so it lives there."""
    rows = (tblObsSceneMap.query
            .filter_by(entity_type='player')
            .order_by(tblObsSceneMap.sort_order, tblObsSceneMap.obs_map_id)
            .all())
    party_ids = {c.character_id for c in _active_party()}
    return [r.entity_id for r in rows
            if r.scene_name and r.entity_id in party_ids]


# ── auto-return to the group shot ─────────────────────────────────────────────

def _cancel_return():
    global _return_timer
    with _return_lock:
        if _return_timer is not None:
            _return_timer.cancel()
            _return_timer = None


def _schedule_return(group_scene, seconds):
    """Drift back to the group shot unless another switch resets the clock."""
    global _return_timer
    import obs_ws

    def _fire():
        try:
            if obs_ws.connected():
                obs_ws.switch_scene(group_scene)
        except Exception as exc:            # never let a timer thread die loud
            log.info('OBS auto-return failed: %s', exc)

    _cancel_return()
    with _return_lock:
        _return_timer = threading.Timer(seconds, _fire)
        _return_timer.daemon = True
        _return_timer.start()


def _after_switch(scene):
    """Arm or cancel the auto-return depending on where we just cut."""
    try:
        seconds = int((appsettingGet('obs_auto_return_s', '') or '0').strip() or 0)
    except (TypeError, ValueError):
        seconds = 0
    group = _special_scene('group')
    if seconds <= 0 or not group or scene == group:
        _cancel_return()                    # already home, or feature off
        return
    _schedule_return(group, seconds)


def _problems(cfg, snap):
    out = []
    if cfg['enabled'] != '1':
        return ['OBS control is disabled.']
    st = snap.get('state')
    if st == 'auth_failed':
        out.append('OBS rejected the password — re-enter it below.')
    elif st == 'unsupported':
        out.append('This OBS build speaks a protocol ScenePlay does not support '
                   '(obs-websocket 5 required — OBS 28 or newer).')
    elif not snap.get('connected'):
        out.append('Not connected to OBS. Is OBS running with '
                   'Tools → WebSocket Server Settings enabled?')
    return out


# ── pages ─────────────────────────────────────────────────────────────────────

@obs_bp.route('/')
@login_required
@dm_required
def broadcast():
    import obs_ws
    cfg = _obs_cfg()
    snap = obs_ws.current_state()
    party = _active_party()
    # ScenePlay scene -> OBS scene: activating an ambience/battle scene can
    # also cut OBS (to the map view, a title card...). Scoped to the active
    # session's campaign, same as the battle map's scene buttons.
    sess = tblSessions.query.filter_by(status='active').first()
    scene_rows = []
    if sess and sess.campaign_id:
        linked = {r.entity_id: r.scene_name for r in
                  tblObsSceneMap.query.filter_by(entity_type='scene').all()}
        for sc in (tblscenes.query
                   .filter_by(campaign_id=sess.campaign_id, active=1)
                   .order_by(tblscenes.orderBy).all()):
            scene_rows.append({'scene_id': sc.scene_ID, 'name': sc.sceneName,
                               'obs_scene': linked.get(sc.scene_ID, '')})
    return render_template('ttrpg/obs_broadcast.html',
                           cfg=cfg, snap=snap,
                           rows=_mapping_rows(party, snap),
                           scene_rows=scene_rows,
                           problems=_problems(cfg, snap),
                           has_party=bool(party))


@obs_bp.route('/api/map-scene', methods=['POST'])
@login_required
@dm_required
def api_map_scene():
    """Bind a ScenePlay scene to an OBS scene (or clear the binding)."""
    data = request.get_json(silent=True) or {}
    try:
        scene_id = int(data.get('scene_id') or 0)
    except (TypeError, ValueError):
        scene_id = 0
    if not scene_id:
        return jsonify({'ok': False, 'error': 'scene_id required'}), 400
    obs_scene = (data.get('scene_name') or '').strip()[:200]
    row = tblObsSceneMap.query.filter_by(entity_type='scene',
                                         entity_id=scene_id).first()
    if not obs_scene:
        if row:
            db.session.delete(row)
            db.session.commit()
        return jsonify({'ok': True, 'scene_name': ''})
    if not row:
        row = tblObsSceneMap(entity_type='scene', entity_id=scene_id, entity_key='')
        db.session.add(row)
    row.scene_name = obs_scene
    row.updated_at = _now()
    db.session.commit()
    return jsonify({'ok': True, 'scene_name': obs_scene})


def obs_scene_for_sceneplay_scene(scene_id):
    """Used by routes/main._activate_scene. Returns '' when the feature is
    off, nothing is mapped, or anything at all goes wrong — activating a
    ScenePlay scene must never fail because of OBS."""
    try:
        if appsettingGet('obs_enabled', '0') != '1':
            return ''
        if (appsettingGet('obs_scene_link', '0') or '0') != '1':
            return ''
        row = tblObsSceneMap.query.filter_by(entity_type='scene',
                                             entity_id=int(scene_id)).first()
        return row.scene_name if row else ''
    except Exception:
        return ''


# ── config ────────────────────────────────────────────────────────────────────

@obs_bp.route('/toggle', methods=['POST'])
@login_required
@dm_required
def toggle():
    import obs_ws
    import relay_guard
    current = appsettingGet('obs_enabled', '0')
    new_val = '0' if current == '1' else '1'
    appsettingSet('obs_enabled', new_val)

    if new_val == '1':
        # Same crash guard as the boot auto-start: if this enable takes the
        # box down, the next start skips OBS instead of boot-looping.
        appsettingSet('obs_boot_tripped', '')
        relay_guard.arm(relay_guard.OBS_GUARD_PATH)
        obs_ws.start(current_app._get_current_object())
        relay_guard.disarm_after_grace(relay_guard.OBS_GUARD_PATH)
        flash('OBS control enabled — connecting.')
    else:
        obs_ws.stop()
        flash('OBS control disabled.')
    return redirect(url_for('obs_bp.broadcast'))


@obs_bp.route('/save-config', methods=['POST'])
@login_required
@dm_required
def save_config():
    import obs_ws
    host = (request.form.get('obs_host', '') or '').strip()
    port = (request.form.get('obs_port', '') or '').strip()
    # Blank password means KEEP the stored one (same convention as the relay
    # secret field) — the form never round-trips the real value.
    password = request.form.get('obs_password', '')

    changed = False
    if host and host != appsettingGet('obs_host', ''):
        appsettingSet('obs_host', host)
        changed = True
    if port.isdigit() and 1 <= int(port) <= 65535 and port != appsettingGet('obs_port', ''):
        appsettingSet('obs_port', port)
        changed = True
    if password:
        if password != appsettingGet('obs_password', ''):
            changed = True
        appsettingSet('obs_password', password)

    transition = (request.form.get('obs_transition', '') or '').strip()
    appsettingSet('obs_transition', transition[:64])
    ms = (request.form.get('obs_transition_ms', '300') or '300').strip()
    if ms.isdigit() and _TRANSITION_MS_MIN <= int(ms) <= _TRANSITION_MS_MAX:
        appsettingSet('obs_transition_ms', ms)

    # Group shot + auto-return: the "don't get stranded on one face" pair.
    group = (request.form.get('obs_group_scene', '') or '').strip()[:200]
    if group:
        _upsert_special_map('group', group)
    else:
        tblObsSceneMap.query.filter_by(entity_type='special', entity_id=0,
                                       entity_key='group').delete()
        db.session.commit()
    secs = (request.form.get('obs_auto_return_s', '0') or '0').strip()
    if secs.isdigit() and 0 <= int(secs) <= 3600:
        appsettingSet('obs_auto_return_s', secs)
        if int(secs) == 0:
            _cancel_return()

    appsettingSet('obs_scene_link',
                  '1' if request.form.get('obs_scene_link') else '0')

    # Shared feed password — same blank-means-keep rule as the OBS password.
    vdo_pw = request.form.get('obs_vdo_password', '')
    if vdo_pw:
        appsettingSet('obs_vdo_password', vdo_pw[:128])
    elif request.form.get('obs_vdo_password_clear'):
        appsettingSet('obs_vdo_password', '')

    if changed:
        # New host/port/password — reconnect, which also clears a previous
        # auth_failed / unsupported verdict.
        appsettingSet('obs_last_error', '')
        obs_ws.restart()
    flash('OBS settings saved.' + (' Reconnecting.' if changed else ''))
    return redirect(url_for('obs_bp.broadcast'))


# ── JSON API ──────────────────────────────────────────────────────────────────

@obs_bp.route('/api/state')
@login_required
@dm_required
def api_state():
    """Polled by the Broadcast page. Pure in-memory read — no OBS round trip."""
    import obs_ws
    snap = obs_ws.current_state()
    return jsonify({
        'ok': True,
        'connected': snap['connected'],
        'state': snap['state'],
        'current_scene': snap['current_scene'],
        'scenes': snap['scenes'],
        'recording': snap['recording'],
        'streaming': snap['streaming'],
        'obs_version': snap['obs_version'],
        'rows': _mapping_rows(_active_party(), snap),
        'group_scene': _special_scene('group'),
        'last_error': appsettingGet('obs_last_error', ''),
    })


@obs_bp.route('/api/health')
@login_required
@dm_required
def api_health():
    import obs_ws
    cfg = _obs_cfg()
    snap = obs_ws.current_state()
    problems = _problems(cfg, snap)
    return jsonify({'enabled': cfg['enabled'] == '1',
                    'ok': not problems,
                    'problems': problems,
                    'state': snap['state'],
                    'current_scene': snap['current_scene']})


@obs_bp.route('/api/refresh', methods=['POST'])
@login_required
@dm_required
def api_refresh():
    """Force a scene-list re-read (the DM just added scenes in OBS)."""
    import obs_ws
    if not obs_ws.connected():
        return jsonify({'ok': False, 'error': 'OBS not connected'}), 503
    scenes, current = obs_ws.scene_list(refresh=True)
    return jsonify({'ok': True, 'scenes': scenes, 'current_scene': current})


@obs_bp.route('/api/map', methods=['POST'])
@login_required
@dm_required
def api_map():
    """Bind a party member to an OBS scene (or clear the binding)."""
    data = request.get_json(silent=True) or {}
    try:
        character_id = int(data.get('character_id') or 0)
    except (TypeError, ValueError):
        character_id = 0
    if not character_id:
        return jsonify({'ok': False, 'error': 'character_id required'}), 400
    scene = (data.get('scene_name') or '').strip()[:200]

    row = tblObsSceneMap.query.filter_by(entity_type='player',
                                         entity_id=character_id,
                                         entity_key='').first()
    if not scene:
        if row:
            db.session.delete(row)
            db.session.commit()
        return jsonify({'ok': True, 'scene_name': ''})
    if row:
        row.scene_name = scene
        row.updated_at = _now()
    else:
        db.session.add(tblObsSceneMap(entity_type='player', entity_id=character_id,
                                      entity_key='', scene_name=scene,
                                      updated_at=_now()))
    db.session.commit()
    return jsonify({'ok': True, 'scene_name': scene})


@obs_bp.route('/api/switch', methods=['POST'])
@login_required
@dm_required
def api_switch():
    """Put someone on screen. Accepts {character_id} (the sidebar button) or
    {scene} (the manual scene buttons)."""
    import obs_ws
    data = request.get_json(silent=True) or {}
    scene = (data.get('scene') or '').strip()
    character_id = data.get('character_id')

    if not scene and character_id:
        try:
            character_id = int(character_id)
        except (TypeError, ValueError):
            return jsonify({'ok': False, 'error': 'bad character_id'}), 400
        row = tblObsSceneMap.query.filter_by(entity_type='player',
                                             entity_id=character_id,
                                             entity_key='').first()
        if not row or not row.scene_name:
            return jsonify({'ok': False, 'need_map': True,
                            'error': 'No OBS scene is mapped to this player yet.'}), 409
        scene = row.scene_name
    if not scene:
        return jsonify({'ok': False, 'error': 'scene or character_id required'}), 400

    if not obs_ws.connected():
        return jsonify({'ok': False, 'error': 'OBS is not connected.',
                        'state': obs_ws.state()}), 503

    transition = appsettingGet('obs_transition', '') or None
    try:
        ms = int(appsettingGet('obs_transition_ms', '300') or 300)
    except (TypeError, ValueError):
        ms = 300
    err = _do_switch(scene)
    if err:
        return err
    return jsonify({'ok': True, 'current_scene': scene,
                    'character_id': character_id or None})


def _do_switch(scene):
    """Switch + arm the auto-return. Returns a Flask error response, or None."""
    import obs_ws
    transition = appsettingGet('obs_transition', '') or None
    try:
        ms = int(appsettingGet('obs_transition_ms', '300') or 300)
    except (TypeError, ValueError):
        ms = 300
    try:
        obs_ws.switch_scene(scene, transition=transition, duration_ms=ms)
    except obs_ws.ObsRejected as exc:
        # 600 ResourceNotFound: the scene was renamed or deleted in OBS.
        if exc.code == 600:
            return jsonify({'ok': False, 'error':
                            f'OBS has no scene named "{scene}" any more.'}), 404
        obs_ws._record_error('switch', exc)
        return jsonify({'ok': False, 'error': f'OBS refused: {exc.comment or exc}'}), 502
    except obs_ws.ObsUnavailable as exc:
        obs_ws._record_error('switch', exc)
        return jsonify({'ok': False, 'error': 'Lost the OBS connection.'}), 503
    _after_switch(scene)
    return None


@obs_bp.route('/api/next', methods=['POST'])
@login_required
@dm_required
def api_next():
    """Walk the camera rotation. {direction: 1|-1} steps relative to whoever
    is on screen NOW (read from OBS's own state, so switching inside OBS keeps
    the rotation in sync); {position: N} jumps straight to the Nth player,
    which is what the number keys use."""
    import obs_ws
    data = request.get_json(silent=True) or {}
    order = _rotation_order()
    if not order:
        return jsonify({'ok': False, 'error':
                        'No players are mapped to OBS scenes yet.'}), 409
    if not obs_ws.connected():
        return jsonify({'ok': False, 'error': 'OBS is not connected.'}), 503

    mapped = _scene_map()
    position = data.get('position')
    if position is not None:
        try:
            idx = int(position) - 1
        except (TypeError, ValueError):
            return jsonify({'ok': False, 'error': 'bad position'}), 400
        if not 0 <= idx < len(order):
            return jsonify({'ok': False,
                            'error': f'Only {len(order)} players are mapped.'}), 409
    else:
        try:
            step = int(data.get('direction', 1)) or 1
        except (TypeError, ValueError):
            step = 1
        current = obs_ws.current_state().get('current_scene', '')
        here = next((i for i, cid in enumerate(order)
                     if mapped.get(cid) == current), None)
        # Not on anyone's camera (group shot, a title card, OBS switched by
        # hand): Next starts at the top of the rotation rather than jumping.
        idx = 0 if here is None else (here + step) % len(order)

    character_id = order[idx]
    err = _do_switch(mapped[character_id])
    if err:
        return err
    return jsonify({'ok': True, 'current_scene': mapped[character_id],
                    'character_id': character_id, 'position': idx + 1})


@obs_bp.route('/api/group', methods=['POST'])
@login_required
@dm_required
def api_group():
    """Back to the group shot — the 'everyone on screen' escape hatch."""
    group = _special_scene('group')
    if not group:
        return jsonify({'ok': False, 'error':
                        'No group scene is set on the Broadcast page.'}), 409
    err = _do_switch(group)
    if err:
        return err
    return jsonify({'ok': True, 'current_scene': group})


@obs_bp.route('/api/reorder', methods=['POST'])
@login_required
@dm_required
def api_reorder():
    """Move a player up/down the camera rotation."""
    data = request.get_json(silent=True) or {}
    try:
        character_id = int(data.get('character_id') or 0)
        delta = int(data.get('delta') or 0)
    except (TypeError, ValueError):
        return jsonify({'ok': False, 'error': 'bad request'}), 400
    order = _rotation_order()
    if character_id not in order or delta not in (-1, 1):
        return jsonify({'ok': False, 'error': 'not in the rotation'}), 409
    i = order.index(character_id)
    j = i + delta
    if not 0 <= j < len(order):
        return jsonify({'ok': True, 'order': order})     # already at the end
    order[i], order[j] = order[j], order[i]
    rows = {r.entity_id: r for r in
            tblObsSceneMap.query.filter_by(entity_type='player').all()}
    for pos, cid in enumerate(order):
        if cid in rows:
            rows[cid].sort_order = pos
    db.session.commit()
    return jsonify({'ok': True, 'order': order})


@obs_bp.route('/api/create-scene', methods=['POST'])
@login_required
@dm_required
def api_create_scene():
    """Build an OBS scene showing this player's feed, and map them to it."""
    import obs_ws
    data = request.get_json(silent=True) or {}
    try:
        character_id = int(data.get('character_id') or 0)
    except (TypeError, ValueError):
        character_id = 0
    char = db.session.get(tblCharacters, character_id) if character_id else None
    if not char:
        return jsonify({'ok': False, 'error': 'unknown character'}), 404
    url = char.video_view_url()
    if not url:
        return jsonify({'ok': False, 'need_feed': True, 'error':
                        f'{char.name} has no camera feed yet — send them the '
                        f'link from the Camera column first.'}), 409
    if not obs_ws.connected():
        return jsonify({'ok': False, 'error': 'OBS is not connected.'}), 503

    scene_name = _scene_name_for(char)
    source_name = f'{scene_name} Feed'
    try:
        scene_name, source_name, warnings = obs_ws.create_player_scene(
            scene_name, source_name, url)
    except obs_ws.ObsRejected as exc:
        obs_ws._record_error('create-scene', exc)
        return jsonify({'ok': False, 'error': f'OBS refused: {exc.comment or exc}'}), 502
    except obs_ws.ObsUnavailable as exc:
        obs_ws._record_error('create-scene', exc)
        return jsonify({'ok': False, 'error': 'Lost the OBS connection.'}), 503

    _upsert_player_map(character_id, scene_name, source_name, auto_created=1)
    obs_ws.scene_list(refresh=True)
    return jsonify({'ok': True, 'scene_name': scene_name, 'warnings': warnings})


def _scene_name_for(char):
    clean = re.sub(r'[\x00-\x1f]', '', char.name or '').strip() or f'Player {char.character_id}'
    return f'Player - {clean}'[:200]


def _upsert_player_map(character_id, scene_name, source_name=None, auto_created=None):
    row = tblObsSceneMap.query.filter_by(entity_type='player',
                                         entity_id=character_id,
                                         entity_key='').first()
    if not row:
        row = tblObsSceneMap(entity_type='player', entity_id=character_id,
                             entity_key='', sort_order=_next_sort_order())
        db.session.add(row)
    row.scene_name = scene_name
    if source_name is not None:
        row.source_name = source_name
    if auto_created is not None:
        row.auto_created = auto_created
    row.updated_at = _now()
    db.session.commit()
    return row


def _next_sort_order():
    rows = tblObsSceneMap.query.filter_by(entity_type='player').all()
    return max([r.sort_order or 0 for r in rows], default=-1) + 1


def _upsert_special_map(key, scene_name):
    row = tblObsSceneMap.query.filter_by(entity_type='special', entity_id=0,
                                         entity_key=key).first()
    if not row:
        row = tblObsSceneMap(entity_type='special', entity_id=0, entity_key=key)
        db.session.add(row)
    row.scene_name = scene_name
    row.updated_at = _now()
    db.session.commit()
    return row


# ── player self-service: my camera ────────────────────────────────────────────
# The player never types a URL. ScenePlay mints a stream id, shows the push
# link plus a QR (scan it on a phone — the usual setup is laptop for the map,
# phone for the camera), and OBS loads the matching view URL.
#
# VDO.ninja is HTTPS-only and this page is normally served over plain LAN
# HTTP, so the capture must NEVER be embedded in an iframe here: camera
# permission is refused when the parent isn't a secure context. Top-level
# navigation to vdo.ninja works fine, which is why this is a link and a QR
# rather than an embed.

def _new_stream_id():
    alphabet = string.ascii_lowercase + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(_STREAM_ID_LEN))


def _normalize_feed_url(url):
    """Validator for a player-supplied feed URL.

    Deliberately NOT the relay's _normalize_device_url, which is a host[:port]
    check that rejects paths and query strings — the whole point of a
    VDO.ninja link is its query string. Empty clears the override."""
    url = (url or '').strip()
    if not url:
        return ''
    if len(url) > _MAX_FEED_URL:
        raise ValueError('That URL is too long.')
    if not re.match(r'^https?://', url, re.I):
        raise ValueError('The URL must start with http:// or https://')
    return url


def _own_character(character_id):
    """A player may only touch their own character; the DM may touch anyone's
    (they set feeds up for people who are at the table but not logged in)."""
    char = db.session.get(tblCharacters, character_id)
    if not char:
        abort(404)
    if not current_user.is_dm() and char.user_id != current_user.user_id:
        abort(403)
    return char


@obs_bp.route('/feed/<int:character_id>')
@login_required
def my_feed(character_id):
    char = _own_character(character_id)
    # Mint the id on first visit so the page always has something to show.
    if not char.video_stream_id and not char.video_feed_url:
        char.video_stream_id = _new_stream_id()
        db.session.commit()
    push_url = char.video_push_url()
    return render_template('ttrpg/obs_my_feed.html',
                           char=char,
                           push_url=push_url,
                           view_url=char.video_view_url(),
                           qr_svg=_qr_svg(push_url),
                           is_dm=current_user.is_dm())


@obs_bp.route('/feed/<int:character_id>', methods=['POST'])
@login_required
def save_feed(character_id):
    char = _own_character(character_id)
    action = request.form.get('action', 'save')

    if action == 'regenerate':
        # The old id leaked (or someone else is squatting on the stream).
        char.video_stream_id = _new_stream_id()
        char.video_feed_url = ''
        flash('New camera link generated — the old one no longer works.')
    else:
        try:
            char.video_feed_url = _normalize_feed_url(request.form.get('video_feed_url'))
        except ValueError as exc:
            flash(str(exc))
            return redirect(url_for('obs_bp.my_feed', character_id=character_id))
        if not char.video_feed_url and not char.video_stream_id:
            char.video_stream_id = _new_stream_id()
        flash('Camera settings saved.' if char.video_feed_url
              else 'Custom URL cleared — back to your ScenePlay camera link.')
    db.session.commit()

    # Keep an already-built OBS scene pointed at the new feed, so changing
    # your camera doesn't silently leave OBS showing the old one.
    _repoint_obs_source(char)
    return redirect(url_for('obs_bp.my_feed', character_id=character_id))


def _repoint_obs_source(char):
    row = tblObsSceneMap.query.filter_by(entity_type='player',
                                         entity_id=char.character_id,
                                         entity_key='').first()
    if not row or not row.source_name:
        return
    try:
        import obs_ws
        if obs_ws.connected():
            obs_ws.set_browser_url(row.source_name, char.video_view_url())
    except Exception as exc:                # never block the player's save
        log.info('Could not repoint OBS source for %s: %s', char.name, exc)


def _qr_svg(url):
    """Inline SVG QR for the push link. Generated LOCALLY — never via an
    external QR service, because the stream id is a capability secret.
    Returns '' when the optional qrcode package isn't installed; the page
    still shows the link and a Copy button."""
    if not url:
        return ''
    try:
        import io
        import qrcode
        import qrcode.image.svg
    except ImportError:
        return ''
    try:
        qr = qrcode.QRCode(box_size=10, border=2)
        qr.add_data(url)
        qr.make(fit=True)
        buf = io.BytesIO()
        qr.make_image(image_factory=qrcode.image.svg.SvgPathImage).save(buf)
        svg = buf.getvalue().decode('utf-8')
        # Drop the XML prolog so it can be inlined straight into the page.
        return svg.split('?>', 1)[-1].strip()
    except Exception:
        return ''
