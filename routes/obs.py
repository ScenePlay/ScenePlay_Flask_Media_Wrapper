"""OBS Studio control — the DM's Broadcast page and the go-live API.

Click a party member (here or on the battle map sidebar) and OBS cuts its
PROGRAM scene to that player's camera. Studio mode is deliberately not used:
this table cuts straight to program.

Everything talks to obs_ws, which holds a persistent socket — so a call here
either answers immediately or fails fast on an in-memory `connected()` check.
No queueing: the DM needs to know whether the cut happened.
"""
import logging
import os
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
import obs_layout

log = logging.getLogger(__name__)

obs_bp = Blueprint('obs_bp', __name__, url_prefix='/ttrpg/obs')

@obs_bp.after_request
def _no_store(resp):
    """Nothing this blueprint serves may be cached.

    The map and card sources poll for live state, and OBS's browser source is
    a plain Chromium: with no cache headers a browser may heuristically cache
    a JSON response and go on serving it, freezing the map on stream while the
    table plays on. Everything here is either live state or a token-gated
    render, so no-store is right across the board."""
    resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    resp.headers['Pragma'] = 'no-cache'
    return resp


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
        'map_scene':     map_scene_name(),
        'panel_on':      '1' if panel_on() else '0',
        'panel_side':     panel_side(),
        'panel_fraction': str(panel_fraction()),
        'title_h':       ('%g' % title_height()),
        'panel_title':   (appsettingGet('obs_panel_title', '') or ''),
        'info_text':     (appsettingGet('obs_info_text', '') or ''),
        'party_bg':      (appsettingGet('obs_party_bg', '') or ''),
        'portal_url':    portal_login_url(),
        'panel_poll':    ('%g' % panel_poll_s()),
        'pre':           show_cfg('pre'),
        'intermission':  show_cfg('intermission'),
        'post':          show_cfg('post'),
        'images':        image_slots(),
        'title_positions': TITLE_POSITIONS,
        'title_image':   (appsettingGet('obs_title_image', '') or '').strip(),
        'map_mode':      map_mode(),
        'map_zoom':      appsettingGet('obs_map_zoom', '1') or '1',
        'map_zoom_max':  (appsettingGet('obs_map_zoom_max', '') or '').strip() or '2.2',
        'map_zoom_hold': (appsettingGet('obs_map_zoom_hold_s', '') or '').strip() or '6',
        'card_poll': ('%g' % card_poll_s()),
        'tile_anim_ms': ('%g' % _tile_anim_ms()),
        # set by app.py's boot guard when a start crashed during OBS bring-up
        'boot_tripped':  appsettingGet('obs_boot_tripped', ''),
        'last_error':    appsettingGet('obs_last_error', ''),
    }


# ── the DM's own tile ─────────────────────────────────────────────────────────
# The DM narrates, plays every NPC and does most of the talking, so they get a
# tile like anyone else. They have no tblCharacters row, so this shim quacks
# like one: a negative id keeps it distinct from any real character while
# flowing through the same layout, rotation, fallback and card code unchanged.

DM_TILE_ID = -1
_MANAGED_PREFIXES = ('Player - ', 'DM - ')
# Order matters: the no-argument /api/map-mode call steps through this list, so
# this is the order the sidebar button and the V hotkey cycle in.
MAP_MODES = ('auto', '2d', '3d')
CARD_POLL_DEFAULT = 10.0


class _DmTile:
    """Character-shaped stand-in for the DM. Feed identity lives in app
    settings rather than a character row."""
    character_id = DM_TILE_ID
    portrait_path = ''
    hp_current = 0
    hp_max = 0
    ac = 0
    conditions = ()

    def __init__(self, name):
        self.name = name
        self.video_stream_id = (appsettingGet('obs_dm_stream_id', '') or '').strip()
        self.video_feed_url = (appsettingGet('obs_dm_feed_url', '') or '').strip()

    def has_feed(self):
        return bool(self.video_feed_url or self.video_stream_id)

    def video_view_url(self):
        from models.ttrpg import _vdo_url
        if self.video_feed_url:
            return self.video_feed_url
        return _vdo_url('view', self.video_stream_id) if self.video_stream_id else ''

    def video_push_url(self):
        from models.ttrpg import _vdo_url
        if self.video_feed_url or not self.video_stream_id:
            return ''
        return _vdo_url('push', self.video_stream_id)

    def hp_pct(self):
        return 0


def dm_tile_enabled():
    return (appsettingGet('obs_dm_enabled', '1') or '1') == '1'


def dm_name():
    from models.user import tblUsers
    row = tblUsers.query.filter_by(role='dm', active=1).first()
    return (row.display_name if row and row.display_name else 'Dungeon Master')


def dm_tile():
    return _DmTile(dm_name())


def dm_player_name():
    """Login behind the DM tile. dm_name() already prefers display_name for
    the tile's title, so this shows the account it belongs to instead of
    repeating the same string twice."""
    from models.user import tblUsers
    row = tblUsers.query.filter_by(role='dm', active=1).first()
    return (row.username or '') if row else ''


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
    overrides = _card_overrides()
    benched = offstage_ids()
    rows = []
    for char in party:
        scene = mapped.get(char.character_id, '')
        rows.append({
            'on_stream': char.character_id not in benched,
            'character_id': char.character_id,
            'name': char.name,
            'scene': scene,
            'missing': bool(scene) and bool(known) and scene not in known,
            'live': bool(scene) and scene == snap.get('current_scene'),
            'feed': _feed_state(char, presence),
            'has_custom_url': bool(char.video_feed_url),
            'show_card': char.character_id in overrides,
            'showing': 'card' if _tile_url(char, presence, overrides).startswith(
                _card_base()) else 'camera',
            'pos': order.index(char.character_id) + 1 if char.character_id in order else 0,
        })
    rows.sort(key=lambda r: (r['pos'] == 0, r['pos'], r['name'].lower()))
    return rows


def _rotation_order():
    """Character ids in turn order — what Next/Prev and the number keys walk.

    This is the party scene's tile order, so pressing 3 always features the
    third tile ON SCREEN — benched players are not counted, or the keys would
    stop lining up with what the audience sees. A player with no camera still
    has a stat-card tile and keeps their turn."""
    return [c.character_id for c in _ordered_party()]


# ── camera drop-out watch ─────────────────────────────────────────────────────
# OBS can't tell us a browser source has no VIDEO — it is rendering a page
# either way — so a dropped camera would otherwise sit on stream as a black
# tile. This watches the signals we do have (relay presence, plus the DM's
# manual pin) and swaps that player's tile to their stat card, then back when
# they return. Only the tile's URL changes: its cell, size and turn position
# all stay put, so the grid never moves.
#
# Presence only covers players logged into the remote portal. Someone sitting
# at the table with no portal login reads as 'ready', never 'stale', and is
# never swapped automatically — that is what the manual pin is for.

_tile_urls = {}                  # character_id -> URL last pushed to OBS
_tile_rects = {}                 # character_id -> rect last placed, so the
                                 # spotlight can animate FROM where a tile
                                 # actually is rather than snapping
_input_settings = {}             # source name -> (url, w, h) last pushed, so a
                                 # sync that changes nothing writes nothing
_watch_timer = None
_watch_lock = threading.Lock()
DEFAULT_WATCH_S = 20


def _watch_seconds():
    try:
        return int((appsettingGet('obs_feed_watch_s', '') or DEFAULT_WATCH_S))
    except (TypeError, ValueError):
        return DEFAULT_WATCH_S


def refresh_tiles():
    """Re-point any tile whose source should have changed. Cheap: it only
    talks to OBS for tiles that actually differ, so the usual pass is a dict
    comparison and no traffic at all. Returns the list of swapped names."""
    import obs_ws
    if not obs_ws.connected():
        return []
    presence = _presence()
    overrides = _card_overrides()
    swapped = []
    for char in _ordered_party():
        want = _tile_url(char, presence, overrides)
        if _tile_urls.get(char.character_id) == want:
            continue
        try:
            source = _source_name_for(char)
            obs_ws.set_browser_url(source, want)
            _tile_urls[char.character_id] = want
            # Keep the settings cache honest, or the next sync would decide
            # the URL still differs and rewrite it a second time.
            prev = _input_settings.get(source)
            if prev:
                _input_settings[source] = (want, prev[1], prev[2])
            swapped.append(char.name)
        except (obs_ws.ObsRejected, obs_ws.ObsUnavailable) as exc:
            # The scene may not be built yet — not worth a stack trace.
            log.info('Tile refresh skipped for %s: %s', char.name, exc)
    if swapped:
        log.info('OBS tiles swapped for: %s', ', '.join(swapped))
    return swapped


def start_feed_watch(app_obj):
    """Idempotent repeating check. Runs only while OBS is enabled — it
    reschedules itself and simply does nothing when the feature is off."""
    global _watch_timer
    seconds = _watch_seconds()
    if seconds <= 0:
        return

    def _tick():
        try:
            with app_obj.app_context():
                if appsettingGet('obs_enabled', '0') == '1':
                    refresh_tiles()
        except Exception as exc:          # a watchdog must never die loudly
            log.info('OBS feed watch failed: %s', exc)
        finally:
            start_feed_watch(app_obj)     # reschedule regardless

    with _watch_lock:
        if _watch_timer is not None:
            _watch_timer.cancel()
        _watch_timer = threading.Timer(seconds, _tick)
        _watch_timer.daemon = True
        _watch_timer.start()


def stop_feed_watch():
    global _watch_timer
    with _watch_lock:
        if _watch_timer is not None:
            _watch_timer.cancel()
            _watch_timer = None


# ── who currently has the turn ────────────────────────────────────────────────
# The party scene never changes, so "who is featured" can't be read back from
# OBS's current scene the way a cut-based setup would. Persist it instead, so
# Next/Previous still work after an app restart or from a second browser tab.

def featured_id():
    raw = (appsettingGet('obs_featured_id', '') or '').strip()
    try:
        return int(raw) or None
    except (TypeError, ValueError):
        return None


def _set_featured(character_id):
    appsettingSet('obs_featured_id', str(character_id or ''))


# ── auto-return: drift back to an even table ──────────────────────────────────

def _cancel_return():
    global _return_timer
    with _return_lock:
        if _return_timer is not None:
            _return_timer.cancel()
            _return_timer = None


def _schedule_return(app_obj, seconds):
    """Un-feature after a quiet spell, so a session never sits stranded on one
    enlarged face. Needs the real app object: this fires on a timer thread,
    which has no request context of its own."""
    global _return_timer

    def _fire():
        try:
            with app_obj.app_context():
                import obs_ws
                if obs_ws.connected():
                    _unfeature()
        except Exception as exc:            # never let a timer thread die loud
            log.info('OBS auto-return failed: %s', exc)

    _cancel_return()
    with _return_lock:
        _return_timer = threading.Timer(seconds, _fire)
        _return_timer.daemon = True
        _return_timer.start()


def _unfeature():
    """Back to an even table (or the DM's dedicated wide shot, if they set
    one). Safe to call from a timer thread.

    The grid is levelled FIRST and ALWAYS. Featuring reflows the party scene,
    so cutting to a wide shot without levelling would strand a doubled tile
    behind it — and when the configured wide shot IS the party scene (the
    obvious thing to set it to) the cut is a no-op and the spotlight simply
    never goes away."""
    import obs_ws
    _sync_party_scene(featured_id=None)
    group = _special_scene('group')
    if group and obs_ws.current_state().get('current_scene') != group:
        obs_ws.switch_scene(group)
    _set_featured(None)
    _cancel_return()


def _after_switch(scene):
    """Arm or cancel the auto-return. `scene` is '' when we just featured a
    player (nothing was cut), which is exactly when the clock should run."""
    try:
        seconds = int((appsettingGet('obs_auto_return_s', '') or '0').strip() or 0)
    except (TypeError, ValueError):
        seconds = 0
    group = _special_scene('group')
    # Already home: on the wide shot, or on the party scene with nobody
    # featured. Nothing to drift back to.
    if seconds <= 0 or (scene and scene == group) or (scene and not group):
        _cancel_return()
        return
    _schedule_return(current_app._get_current_object(), seconds)


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
    # First visit auto-configures where OBS fetches stat cards from: whatever
    # address the DM is reaching ScenePlay on is one OBS can reach too, in the
    # normal same-machine / same-LAN setup.
    if not (appsettingGet('obs_card_base', '') or '').strip():
        appsettingSet('obs_card_base', request.host_url.rstrip('/'))
    cfg = _obs_cfg()
    snap = obs_ws.current_state()
    # Benched players are listed too — greyed out, with the tick that brings
    # them back. Leaving them off would strand them off stream for good.
    party = _ordered_party(include_offstage=True)
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
                           dm_enabled=dm_tile_enabled(),
                           dm_id=DM_TILE_ID,
                           map_token=_map_token(),
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
        start_feed_watch(current_app._get_current_object())
        relay_guard.disarm_after_grace(relay_guard.OBS_GUARD_PATH)
        flash('OBS control enabled — connecting.')
    else:
        obs_ws.stop()
        stop_feed_watch()
        _cancel_return()
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
    appsettingSet('obs_dm_enabled',
                  '1' if request.form.get('obs_dm_enabled') else '0')
    appsettingSet('obs_panel_on',
                  '1' if request.form.get('obs_panel_on') else '0')
    side = (request.form.get('obs_panel_side', '') or 'right').strip().lower()
    appsettingSet('obs_panel_side',
                  side if side in ('left', 'right', 'top', 'bottom') else 'right')
    appsettingSet('obs_panel_title',
                  (request.form.get('obs_panel_title', '') or '').strip()[:120])
    for kind in ('pre', 'intermission', 'post'):
        appsettingSet(f'obs_{kind}_title',
                      (request.form.get(f'obs_{kind}_title', '') or '').strip()[:120])
        pos = (request.form.get(f'obs_{kind}_title_pos', '') or '').strip().lower()
        appsettingSet(f'obs_{kind}_title_pos',
                      pos if pos in TITLE_POSITIONS else 'bottom-center')
    # Kept verbatim, newlines and all: each line is one row in the panel.
    appsettingSet('obs_info_text',
                  (request.form.get('obs_info_text', '') or '')[:4000])
    # Only when the form actually carries it. The mode is a live shot call made
    # from the mode buttons, and this form does not post it — writing a default
    # here would silently snap the stream back every time the DM saved an
    # unrelated map setting.
    if 'obs_map_mode' in request.form:
        mode = (request.form.get('obs_map_mode', '') or 'auto').strip().lower()
        appsettingSet('obs_map_mode', mode if mode in MAP_MODES else 'auto')
    appsettingSet('obs_map_zoom',
                  '1' if request.form.get('obs_map_zoom') else '0')
    for field, lo, hi in (('obs_map_zoom_max', 1.0, 6.0),
                          ('obs_map_zoom_hold_s', 1, 120),
                          ('obs_card_poll_s', 2, 120),
                          ('obs_panel_poll_s', 1, 60),
                          ('obs_title_h', 0, 400),
                          ('obs_tile_anim_ms', 0, 4000),
                          ('obs_panel_fraction', 0.12, 0.6)):
        raw = (request.form.get(field, '') or '').strip()
        try:
            appsettingSet(field, str(min(max(float(raw), lo), hi)))
        except (TypeError, ValueError):
            pass
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
        'rows': _mapping_rows(_ordered_party(include_offstage=True), snap),
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
    """Give a player the turn — {character_id} enlarges their tile in the
    party scene without cutting. {scene} still cuts program to a named scene,
    which is what the manual scene buttons use."""
    import obs_ws
    data = request.get_json(silent=True) or {}
    scene = (data.get('scene') or '').strip()
    character_id = data.get('character_id')

    if not obs_ws.connected():
        return jsonify({'ok': False, 'error': 'OBS is not connected.',
                        'state': obs_ws.state()}), 503

    if not scene and character_id:
        try:
            character_id = int(character_id)
        except (TypeError, ValueError):
            return jsonify({'ok': False, 'error': 'bad character_id'}), 400
        if character_id not in _rotation_order():
            return jsonify({'ok': False, 'need_build': True, 'error':
                            'That player is not in the party scene — build it '
                            'from the Broadcast page first.'}), 409
        payload, err = _do_feature(character_id)
        if err:
            return err
        _set_featured(character_id)
        return jsonify({'ok': True, 'character_id': character_id, **payload})

    if not scene:
        return jsonify({'ok': False, 'error': 'scene or character_id required'}), 400
    err = _do_switch(scene)
    if err:
        return err
    _set_featured(None)
    return jsonify({'ok': True, 'current_scene': scene, 'character_id': None})


def _do_switch(scene):
    """Cut program to a named scene. Still used for the manual scene buttons
    and the ScenePlay-scene link; featuring a PLAYER goes through _do_feature
    instead, which never cuts."""
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


def _do_feature(character_id):
    """Give a player the turn: re-lay-out the party scene with their tile
    enlarged. No program cut — the whole table stays on screen.

    Returns (payload, error_response). Also makes sure program is ON the
    party scene, so the first turn of the night puts it up."""
    import obs_ws
    scene = party_scene_name()
    try:
        result = _sync_party_scene(featured_id=character_id)
        if obs_ws.current_state().get('current_scene') != scene:
            obs_ws.switch_scene(scene)
    except obs_ws.ObsRejected as exc:
        obs_ws._record_error('feature', exc)
        return None, (jsonify({'ok': False,
                               'error': f'OBS refused: {exc.comment or exc}'}), 502)
    except obs_ws.ObsUnavailable as exc:
        obs_ws._record_error('feature', exc)
        return None, (jsonify({'ok': False, 'error': 'Lost the OBS connection.'}), 503)
    _after_switch(scene if character_id is None else '')
    return {'scene': scene, 'featured_id': character_id,
            'warnings': result['warnings']}, None


@obs_bp.route('/api/next', methods=['POST'])
@login_required
@dm_required
def api_next():
    """Walk the turn order. {direction: 1|-1} steps from whoever holds the
    turn now; {position: N} jumps straight to the Nth tile, which is what the
    number keys use."""
    import obs_ws
    data = request.get_json(silent=True) or {}
    order = _rotation_order()
    if not order:
        return jsonify({'ok': False, 'error':
                        'No party members yet — start a session with a party.'}), 409
    if not obs_ws.connected():
        return jsonify({'ok': False, 'error': 'OBS is not connected.'}), 503

    position = data.get('position')
    if position is not None:
        try:
            idx = int(position) - 1
        except (TypeError, ValueError):
            return jsonify({'ok': False, 'error': 'bad position'}), 400
        if not 0 <= idx < len(order):
            return jsonify({'ok': False,
                            'error': f'Only {len(order)} players on screen.'}), 409
    else:
        try:
            step = int(data.get('direction', 1)) or 1
        except (TypeError, ValueError):
            step = 1
        current = featured_id()
        here = order.index(current) if current in order else None
        # Nobody featured (even table, or a fresh session): Next starts at the
        # top of the order rather than jumping into the middle.
        idx = 0 if here is None else (here + step) % len(order)

    character_id = order[idx]
    payload, err = _do_feature(character_id)
    if err:
        return err
    _set_featured(character_id)
    return jsonify({'ok': True, 'character_id': character_id,
                    'position': idx + 1, **payload})


@obs_bp.route('/api/group', methods=['POST'])
@login_required
@dm_required
def api_group():
    """Even the table out again — nobody enlarged. Cuts to a dedicated wide
    shot instead if the DM configured one."""
    import obs_ws
    if not obs_ws.connected():
        return jsonify({'ok': False, 'error': 'OBS is not connected.'}), 503
    # Releasing the pin is part of "even the table out again": otherwise the
    # map would stay locked to whoever was last looked through.
    _set_viewed_character(None)
    try:
        _unfeature()
    except obs_ws.ObsRejected as exc:
        obs_ws._record_error('group', exc)
        return jsonify({'ok': False, 'error': f'OBS refused: {exc.comment or exc}'}), 502
    except obs_ws.ObsUnavailable:
        return jsonify({'ok': False, 'error': 'Lost the OBS connection.'}), 503
    return jsonify({'ok': True, 'current_scene': _special_scene('group')
                    or party_scene_name(), 'character_id': None})


@obs_bp.route('/api/view-player', methods=['POST'])
@login_required
@dm_required
def api_view_player():
    """Show the map through one character's eyes.

    3D when the map can do it (it needs a floorplan AND background art), and
    a held close-up on that character in 2D when it cannot — so the button
    always does something useful rather than being dead on a flat map.

    The render mode it implies is an OVERRIDE that lives with the pin; the
    configured mode is left alone and takes over again on release."""
    import obs_ws
    from models.ttrpg import tblBattleMaps
    data = request.get_json(silent=True) or {}
    try:
        character_id = int(data.get('character_id') or 0)
    except (TypeError, ValueError):
        character_id = 0
    if not character_id:
        return jsonify({'ok': False, 'error': 'character_id required'}), 400
    char = db.session.get(tblCharacters, character_id)
    if not char:
        return jsonify({'ok': False, 'error': 'No such character.'}), 404

    sess = tblSessions.query.filter_by(status='active').first()
    bm = (tblBattleMaps.query.filter_by(session_id=sess.session_id, is_active=1).first()
          if sess else None)
    if bm is None:
        return jsonify({'ok': False, 'error': 'No live battle map.'}), 409
    on_map = any(t.entity_type == 'player' and t.entity_id == character_id
                 for t in bm.tokens)
    if not on_map:
        return jsonify({'ok': False,
                        'error': f'{char.name} has no token on this map.'}), 409

    _set_viewed_character(character_id)
    mode = effective_map_mode(bm, True)
    three_d = mode == '3d'
    # Deliberately NOT written to obs_map_mode. This is a shot call for the
    # moment, not a change of setting: the DM's configured mode (usually
    # auto) has to be exactly what it was once the pin is released.

    scene = None
    if obs_ws.connected():
        scene = _special_scene('map') or map_scene_name()
        try:
            known, _cur = obs_ws.scene_list()
            if scene not in (known or []):
                scene, _warn = ensure_map_scene()
            obs_ws.switch_scene(scene)
        except obs_ws.ObsRejected as exc:
            obs_ws._record_error('view-player', exc)
            scene = None
        except obs_ws.ObsUnavailable:
            scene = None
    return jsonify({'ok': True, 'character_id': character_id,
                    'name': char.name, 'mode': mode,
                    'three_d': three_d, 'current_scene': scene})


# What the sidebar's cut buttons can switch to. Party is included so the DM
# can get back to the table without hunting for it in OBS.
CUT_TARGETS = {
    'map':          ('map',          'battle map'),
    'pre':          ('pre',          'pre-show card'),
    'intermission': ('intermission', 'intermission card'),
    'post':         ('post',         'post-show card'),
    'party':        ('group',        'party scene'),
}


def _cut_scene_name(key):
    """The OBS scene for a cut target, preferring an explicit binding."""
    special, _label = CUT_TARGETS[key]
    scene = _special_scene(special)
    if scene:
        return scene
    return {'map': map_scene_name, 'pre': pre_scene_name,
            'intermission': intermission_scene_name,
            'post': post_scene_name, 'party': party_scene_name}[key]()


@obs_bp.route('/api/cut/<key>', methods=['POST'])
@login_required
@dm_required
def api_cut(key):
    """Put one of the ScenePlay scenes on screen.

    Ensures the scene first where it can be built: a DM who has never run
    Build / refresh party scene would otherwise get "no such scene" from a
    button that looks like it should just work."""
    import obs_ws
    if key not in CUT_TARGETS:
        return jsonify({'ok': False, 'error': f'Unknown target {key!r}'}), 400

    # Choosing a scene ENDS the follow-this-character override, every time —
    # including when the scene is already live. Clicking Map while pinned used
    # to be a no-op (same scene, pin untouched), so the only way out of a
    # character's 3D view was to cut elsewhere and come back.
    #
    # Done before the connected() check on purpose: the pin governs what the
    # map SOURCE renders, which is ScenePlay state and nothing to do with OBS.
    # Releasing it must work even with the rig offline.
    was_pinned = viewed_character_id()
    _set_viewed_character(None)
    unpinned = was_pinned is not None

    if not obs_ws.connected():
        return jsonify({'ok': False, 'error': 'OBS is not connected.',
                        'unpinned': unpinned}), 503
    _special, label = CUT_TARGETS[key]
    scene = _cut_scene_name(key)
    levelled = False
    try:
        # The group shot means EVERYONE equal, so cutting to it also ends any
        # closeup. Without this the button was a one-way door: it put the party
        # scene up still reflowed around a doubled tile, with no way back to
        # the even grid from the map. (The G key already did the right thing
        # via /api/group — the button and the key now agree.)
        if key == 'party' and featured_id() is not None:
            _sync_party_scene(featured_id=None)
            _set_featured(None)
            _cancel_return()
            levelled = True
        known, _current = obs_ws.scene_list()
        if scene not in (known or []):
            if key == 'map':
                scene, _warn = ensure_map_scene()
            elif key in ('pre', 'intermission', 'post'):
                built, _warn = ensure_show_scenes()
                scene = built.get(key, scene)
        obs_ws.switch_scene(scene)
    except obs_ws.ObsRejected as exc:
        obs_ws._record_error(f'cut-{key}', exc)
        if exc.code == 600:
            return jsonify({'ok': False,
                            'error': f'No {label} scene in OBS yet — run '
                                     'Build / refresh party scene.'}), 404
        return jsonify({'ok': False, 'error': f'OBS refused: {exc.comment or exc}'}), 502
    except obs_ws.ObsUnavailable:
        return jsonify({'ok': False, 'error': 'Lost the OBS connection.'}), 503
    return jsonify({'ok': True, 'current_scene': scene, 'target': key,
                    'unpinned': unpinned, 'levelled': levelled})


@obs_bp.route('/api/cut-map', methods=['POST'])
@login_required
@dm_required
def api_cut_map():
    """Kept as its own path: the sidebar shipped against it before the generic
    cut endpoint existed, and an older loaded page may still call it."""
    return api_cut('map')


@obs_bp.route('/api/card-override', methods=['POST'])
@login_required
@dm_required
def api_card_override():
    """Pin a player to their stat card (or release them back to their camera).

    The manual answer to a dropped feed: presence only sees portal players, so
    for anyone at the table this is what the DM reaches for."""
    data = request.get_json(silent=True) or {}
    try:
        character_id = int(data.get('character_id') or 0)
    except (TypeError, ValueError):
        return jsonify({'ok': False, 'error': 'bad character_id'}), 400
    if not character_id:
        return jsonify({'ok': False, 'error': 'character_id required'}), 400
    on = bool(data.get('show_card'))
    _set_card_override(character_id, on)
    swapped = refresh_tiles()
    return jsonify({'ok': True, 'character_id': character_id,
                    'show_card': on, 'swapped': swapped})


def _closeup_rows():
    """Who the DM can cut a closeup to, for the battle map's closeup popup.

    Only the party members actually on the group feed — a benched player has
    no tile, so offering them here could only produce a failed switch. In
    rotation order, so the list reads the same as the number keys and as the
    tiles on screen.

    Carries the PLAYER's name as well as the character's: mid-session the DM
    is usually thinking "get Dave on camera", and every other list in the
    sidebar shows character names only."""
    presence = _presence()
    overrides = _card_overrides()
    featured = featured_id()
    out = []
    for pos, char in enumerate(_ordered_party(), start=1):
        out.append({
            'character_id': char.character_id,
            'name': char.name,
            'player': ('the DM' if char.character_id == DM_TILE_ID
                       else player_name_for(char)),
            'feed': _feed_state(char, presence),
            'showing': ('card' if _tile_url(char, presence, overrides)
                        .startswith(_card_base()) else 'camera'),
            'featured': char.character_id == featured,
            'pos': pos,
        })
    return out


@obs_bp.route('/api/closeups')
@login_required
@dm_required
def api_closeups():
    return jsonify({'ok': True, 'rows': _closeup_rows()})


@obs_bp.route('/api/on-stream', methods=['POST'])
@login_required
@dm_required
def api_on_stream():
    """Bench a player from the party scene, or bring them back.

    For a player missing this episode, or the half of a split party the stream
    isn't with. They keep their session seat and their place in the running
    order — only their tile goes, and the grid re-lays-out around the gap."""
    import obs_ws
    data = request.get_json(silent=True) or {}
    try:
        character_id = int(data.get('character_id') or 0)
    except (TypeError, ValueError):
        return jsonify({'ok': False, 'error': 'bad character_id'}), 400
    if not character_id:
        return jsonify({'ok': False, 'error': 'character_id required'}), 400

    on = bool(data.get('on_stream'))
    _set_offstage(character_id, not on)
    # Benching whoever holds the spotlight would leave the stored featured id
    # pointing at a tile that no longer exists, and the next Next/Previous
    # would step from nowhere. Level the table instead.
    if not on and featured_id() == character_id:
        _set_featured(None)
    if not obs_ws.connected():
        return jsonify({'ok': True, 'character_id': character_id,
                        'on_stream': on, 'warnings': [
                            'OBS is not connected — the party scene will pick '
                            'this up next time it is built.']})
    try:
        result = _sync_party_scene(featured_id=featured_id())
    except obs_ws.ObsRejected as exc:
        obs_ws._record_error('on-stream', exc)
        return jsonify({'ok': False,
                        'error': f'OBS refused: {exc.comment or exc}'}), 502
    except obs_ws.ObsUnavailable:
        return jsonify({'ok': False, 'error': 'Lost the OBS connection.'}), 503
    return jsonify({'ok': True, 'character_id': character_id, 'on_stream': on,
                    'warnings': result['warnings']})


@obs_bp.route('/api/map-mode', methods=['POST'])
@login_required
@dm_required
def api_map_mode():
    """Flip the map source between auto, 2D and 3D mid-play.

    Instant on purpose: this is a shot call made during a session, not a
    setting to fill in and save. The source picks it up on its next state
    poll (~2 s) with no reload, because the mode rides in the state rather
    than the page."""
    data = request.get_json(silent=True) or {}
    want = (data.get('mode') or '').strip().lower()
    if want not in MAP_MODES:
        # No mode given = step to the next one, so the sidebar button and the
        # V hotkey can cycle without knowing the current state.
        cur = map_mode()
        want = MAP_MODES[(MAP_MODES.index(cur) + 1) % len(MAP_MODES)]
    appsettingSet('obs_map_mode', want)
    # Choosing a mode RELEASES any pinned character. The pin outranks the
    # configured mode, so leaving it on made this button look broken: auto
    # never got a turn because the pin was still dictating the render, and
    # the view stayed stuck on whoever was last clicked.
    was_pinned = viewed_character_id()
    _set_viewed_character(None)
    return jsonify({'ok': True, 'mode': want, 'unpinned': was_pinned is not None})


@obs_bp.route('/api/map-reload', methods=['POST'])
@login_required
@dm_required
def api_map_reload():
    """Make OBS re-fetch the map page.

    A browser source loads its page once and keeps it running for as long as
    OBS is open, so a ScenePlay update lands on the server but not on the
    stream: the state keeps polling and looks healthy while the page running
    it is weeks old. Everything else here is state-driven and needs no
    reload, which is exactly what makes this case confusing enough to be
    worth a button."""
    import obs_ws
    if not obs_ws.connected():
        return jsonify({'ok': False, 'error': 'OBS not connected'}), 503
    try:
        obs_ws.refresh_browser_source(MAP_SOURCE_NAME)
    except obs_ws.ObsRejected as e:
        if e.code == 600:
            return jsonify({'ok': False,
                            'error': f'No "{MAP_SOURCE_NAME}" source in OBS yet '
                                     '— add the map to a scene first.'}), 404
        return jsonify({'ok': False, 'error': str(e)}), 502
    except obs_ws.ObsUnavailable as e:
        return jsonify({'ok': False, 'error': str(e)}), 503
    return jsonify({'ok': True, 'source': MAP_SOURCE_NAME})


@obs_bp.route('/api/refresh-tiles', methods=['POST'])
@login_required
@dm_required
def api_refresh_tiles():
    """Force the drop-out check now instead of waiting for the next tick."""
    import obs_ws
    if not obs_ws.connected():
        return jsonify({'ok': False, 'error': 'OBS is not connected.'}), 503
    return jsonify({'ok': True, 'swapped': refresh_tiles()})


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


# ── the party scene ───────────────────────────────────────────────────────────
# One scene holds every player as a tile. Giving someone the turn is a
# TRANSFORM change, not a program cut: the table stays on screen and the
# active player just grows in place, so the audience never loses track of who
# sits where.

def party_scene_name():
    return ((appsettingGet('obs_party_scene', '') or '').strip()
            or 'ScenePlay Party')


def map_scene_name():
    return ((appsettingGet('obs_map_scene', '') or '').strip()
            or 'ScenePlay Map')


def pre_scene_name():
    return ((appsettingGet('obs_pre_scene', '') or '').strip()
            or 'ScenePlay Pre')


def post_scene_name():
    return ((appsettingGet('obs_post_scene', '') or '').strip()
            or 'ScenePlay Post')


def intermission_scene_name():
    return ((appsettingGet('obs_intermission_scene', '') or '').strip()
            or 'ScenePlay Intermission')


# Where a show card's title sits. Nine positions rather than free coordinates:
# the DM is placing one line of text over one image, and a dropdown they can
# get right first time beats an x/y pair they have to nudge on a live stream.
TITLE_POSITIONS = ('top-left', 'top-center', 'top-right',
                   'middle-left', 'middle-center', 'middle-right',
                   'bottom-left', 'bottom-center', 'bottom-right')
SHOW_IMAGE_FRACTION = 0.75      # of the canvas, so the background frames it

# Every image the broadcast uses, in one place: slot -> (setting, filename
# stem, label). Having four near-identical upload handlers scattered down the
# page was how the settings for them ended up scattered down the UI too.
IMAGE_SLOTS = {
    'title':        ('obs_title_image', 'title-card',
                     'Title card — map idle screen and the pre-show'),
    'party_bg':     ('obs_party_bg', 'party-bg',
                     'Background — sits behind every ScenePlay scene'),
    'intermission': ('obs_intermission_image', 'intermission',
                     'Intermission card'),
    'post':         ('obs_post_image', 'post-show', 'Post-show card'),
}


def image_slots():
    """Slot rows for the Broadcast page: what is set, and where it lives."""
    out = []
    for slot, (setting, _stem, label) in IMAGE_SLOTS.items():
        name = (appsettingGet(setting, '') or '').strip()
        out.append({
            'slot': slot, 'label': label, 'file': name,
            'url': (url_for('static', filename=f'uploads/obs/{name}')
                    if name else ''),
        })
    return out


def show_cfg(kind):
    """Image, title and title placement for the pre- or post-show card.

    'pre' deliberately shares obs_title_image with the map's idle card: it is
    the same "we're about to start" art, and keeping one setting means the DM
    uploads it once instead of keeping two copies in step."""
    slot = {'pre': 'title', 'post': 'post', 'intermission': 'intermission'}[kind]
    img = (appsettingGet(IMAGE_SLOTS[slot][0], '') or '').strip()
    pos = (appsettingGet(f'obs_{kind}_title_pos', '') or '').strip().lower()
    return {
        'image': img,
        'image_url': (f'{_card_base()}/static/uploads/obs/{img}' if img else ''),
        'title': (appsettingGet(f'obs_{kind}_title', '') or '').strip(),
        'pos': pos if pos in TITLE_POSITIONS else 'bottom-center',
    }


MAP_SOURCE_NAME = 'ScenePlay Battle Map'


PANEL_TOKEN_KEY = 'obs-panel'
BG_DIR = os.path.join('static', 'uploads', 'obs')


def panel_on():
    """The information panel is on by default: an empty strip is easy to spot
    and turn off, whereas a missing one just looks like the layout is wrong."""
    return (appsettingGet('obs_panel_on', '1') or '1') == '1'


def panel_side():
    side = (appsettingGet('obs_panel_side', 'right') or 'right').strip().lower()
    return side if side in ('left', 'right', 'top', 'bottom') else 'right'


def panel_fraction():
    try:
        return min(max(float((appsettingGet('obs_panel_fraction', '') or '').strip()
                             or obs_layout.DEFAULT_PANEL_FRACTION), 0.12), 0.6)
    except (TypeError, ValueError):
        return obs_layout.DEFAULT_PANEL_FRACTION


def title_height():
    try:
        return min(max(float((appsettingGet('obs_title_h', '') or '').strip()
                             or obs_layout.DEFAULT_TITLE_H), 0), 400)
    except (TypeError, ValueError):
        return obs_layout.DEFAULT_TITLE_H


def _frame_areas(canvas_w, canvas_h):
    return obs_layout.frame_areas(canvas_w, canvas_h, panel_side(),
                                  panel_fraction(), title_height(), panel_on())


def _panel_token():
    import hashlib
    import hmac
    key = (current_app.secret_key or '').encode() or b'sceneplay'
    return hmac.new(key, PANEL_TOKEN_KEY.encode(), hashlib.sha256).hexdigest()[:32]


def panel_url(mode='info'):
    return (f'{_card_base()}{obs_bp.url_prefix}/panel'
            f'?t={_panel_token()}&mode={mode}')


def ensure_map_scene():
    """A dedicated full-canvas Map scene to cut to. The SAME source is reused
    in the party scene when the panel is on — obs-websocket lets one input
    live in several scenes with independent transforms."""
    import obs_ws
    scene = map_scene_name()
    obs_ws.ensure_scene(scene)
    snap = obs_ws.current_state()
    w = snap.get('base_width') or 1920
    h = snap.get('base_height') or 1080
    # Map and dice SHARE the canvas rather than the dice covering a corner of
    # the map. The SAME frame_areas call the party scene uses, title strip
    # included, so the roll feed is the identical size and position in both
    # scenes and cutting between them doesn't shift it.
    areas = obs_layout.frame_areas(w, h, panel_side(), panel_fraction(),
                                   title_h=title_height(), panel_on=True)
    mrect, drect = areas['tiles'], areas['panel']

    item_id, warnings = obs_ws.ensure_browser_input(
        scene, MAP_SOURCE_NAME, map_url(), int(mrect[2]), int(mrect[3]))
    if item_id is not None:
        obs_ws.place_item(scene, item_id, {'x': mrect[0], 'y': mrect[1],
                                           'w': mrect[2], 'h': mrect[3]})
        obs_ws.set_item_enabled(scene, item_id, True)

    # The roll feed takes the SAME rect the party's info panel uses, and the
    # title strip is the same input as the party's — so cutting between the
    # two scenes moves neither.
    for src, rect, mode, label in (
            (TITLE_SOURCE_NAME, areas['title'], 'title', 'title strip'),
            (DICE_SOURCE_NAME, drect, 'dice', 'dice feed')):
        if rect is None:
            continue
        try:
            sid, warn = obs_ws.ensure_browser_input(
                scene, src, panel_url(mode), int(rect[2]), int(rect[3]))
            warnings.extend(warn)
            if sid is not None:
                obs_ws.place_item(scene, sid, {'x': rect[0], 'y': rect[1],
                                               'w': rect[2], 'h': rect[3]})
                obs_ws.set_item_enabled(scene, sid, True)
        except (obs_ws.ObsRejected, obs_ws.ObsUnavailable) as exc:
            warnings.append(f'Could not place the {label} ({exc}).')

    _place_background(scene, w, h, warnings)
    _upsert_special_map('map', scene)
    obs_ws.scene_list(refresh=True)
    return scene, warnings


SHOW_SOURCE = {'pre': 'ScenePlay Pre-Show',
               'intermission': 'ScenePlay Intermission Card',
               'post': 'ScenePlay Post-Show'}


def ensure_show_scenes():
    """The pre-show and post-show cards, one scene each.

    Each is just the shared background with a card over it, so the art the
    rest of the stream uses carries through the top and tail instead of the
    show opening on an unrelated screen."""
    import obs_ws
    warnings = []
    snap = obs_ws.current_state()
    w = snap.get('base_width') or 1920
    h = snap.get('base_height') or 1080
    scenes = {}
    for kind, name_fn in (('pre', pre_scene_name),
                          ('intermission', intermission_scene_name),
                          ('post', post_scene_name)):
        scene = name_fn()
        obs_ws.ensure_scene(scene)
        try:
            item_id, warn = obs_ws.ensure_browser_input(
                scene, SHOW_SOURCE[kind], panel_url(kind), w, h)
            warnings.extend(warn)
            if item_id is not None:
                obs_ws.place_item(scene, item_id,
                                  {'x': 0, 'y': 0, 'w': w, 'h': h})
                obs_ws.set_item_enabled(scene, item_id, True)
        except (obs_ws.ObsRejected, obs_ws.ObsUnavailable) as exc:
            warnings.append(f'Could not place the {kind}-show card ({exc}).')
        _place_background(scene, w, h, warnings)
        _upsert_special_map(kind, scene)
        scenes[kind] = scene
    obs_ws.scene_list(refresh=True)
    return scenes, warnings


def _source_name_for(char):
    return f'{_scene_name_for(char)} Cam'


def _id_set(setting):
    """Character ids stored as a comma-separated setting. Kept in settings
    rather than new columns so existing installs need no migration."""
    raw = (appsettingGet(setting, '') or '').strip()
    out = set()
    for part in raw.split(','):
        part = part.strip()
        # lstrip('-'): the DM tile's id is negative
        if part.lstrip('-').isdigit():
            out.add(int(part))
    return out


def _set_id_flag(setting, character_id, on):
    ids = _id_set(setting)
    ids.add(character_id) if on else ids.discard(character_id)
    appsettingSet(setting, ','.join(str(i) for i in sorted(ids)))


def _card_overrides():
    """Character ids the DM has pinned to their stat card."""
    return _id_set('obs_card_override')


def _set_card_override(character_id, on):
    _set_id_flag('obs_card_override', character_id, on)


def offstage_ids():
    """Character ids benched from the party scene — no tile, no turn.

    Stores who is OFF rather than who is on, so an install that has never
    touched this (an empty setting) has the whole party on stream. For a
    player who can't make this episode, or the half of a split party the
    stream isn't following: they keep their session seat, their stats and
    their place in the running order the moment they come back."""
    return _id_set('obs_offstage')


def _set_offstage(character_id, on):
    _set_id_flag('obs_offstage', character_id, on)


def player_name_for(char):
    """The human playing this character, for the overlay.

    display_name when the account has one, else the login. Empty when the
    character isn't claimed by an account — the overlay just omits the line
    rather than showing a blank field."""
    u = getattr(char, 'user', None)
    if not u:
        return ''
    return (getattr(u, 'display_name', '') or '').strip() or (u.username or '').strip()


def tile_url(character_id):
    # Same reason card_url does this: Flask's <int:> converter never matches a
    # negative number, so the DM tile (id -1) needs its own leaf. Without it
    # the DM's camera tile was a 404 in OBS.
    leaf = 'dm' if character_id == DM_TILE_ID else str(character_id)
    return (f'{_card_base()}{obs_bp.url_prefix}/tile/{leaf}'
            f'?t={_card_token(character_id)}')


def _tile_url(char, presence=None, overrides=None):
    """What this player's tile should be showing right now.

    Their stat card stands in whenever the camera isn't going to show
    anything: no feed configured, the DM pinned the card, or the relay says
    they dropped. A tile is never an empty black box, and because the card
    occupies the SAME cell, nothing on the grid moves when it swaps."""
    if overrides is None:
        overrides = _card_overrides()
    if char.character_id in overrides:
        return card_url(char.character_id)
    if not char.video_view_url():
        return card_url(char.character_id)
    if presence is None:
        presence = _presence()
    if _feed_state(char, presence) == 'stale':
        # They had a camera and the relay stopped hearing from them.
        return card_url(char.character_id)
    # Not the bare feed: the tile page frames it and lays the character's name,
    # player and HP over the bottom, so one source carries both.
    return tile_url(char.character_id)


@obs_bp.route('/api/build-party', methods=['POST'])
@login_required
@dm_required
def api_build_party():
    """Create/refresh the party scene: every party member gets a tile, laid
    out on the grid. Idempotent — run it again after the party changes.

    Rebuilding KEEPS whoever holds the spotlight: dropping back to the even
    grid here would leave the stored featured id disagreeing with what is on
    screen, and the next Next/Previous would step from a player the audience
    can no longer see is featured."""
    import obs_ws
    if not obs_ws.connected():
        return jsonify({'ok': False, 'error': 'OBS is not connected.'}), 503
    # Forget what we believe OBS holds, so this really is the repair button:
    # ordinary syncs skip writing settings that already match, which would
    # otherwise make a hand-edited source impossible to put back from here.
    _input_settings.clear()
    try:
        result = _sync_party_scene(featured_id=featured_id())
        map_scene, map_warn = ensure_map_scene()
        result['warnings'].extend(map_warn)
        result['map_scene'] = map_scene
        show_scenes, show_warn = ensure_show_scenes()
        result['warnings'].extend(show_warn)
        result['show_scenes'] = show_scenes
    except obs_ws.ObsRejected as exc:
        obs_ws._record_error('build-party', exc)
        return jsonify({'ok': False, 'error': f'OBS refused: {exc.comment or exc}'}), 502
    except obs_ws.ObsUnavailable as exc:
        obs_ws._record_error('build-party', exc)
        return jsonify({'ok': False, 'error': 'Lost the OBS connection.'}), 503
    start_feed_watch(current_app._get_current_object())
    return jsonify({'ok': True, **result})


DEFAULT_TILE_ANIM_MS = 700


def _ensure_input(scene, source, url, width, height, warnings):
    """ensure_browser_input, but only writing the source's settings when they
    have actually changed.

    Writing them re-renders the page even when nothing differs — which blanks a
    live camera for an instant. Doing that to every tile on every spotlight
    change is the flash across the whole grid."""
    import obs_ws
    want = (url, int(width), int(height))
    item_id, warn = obs_ws.ensure_browser_input(
        scene, source, url, width, height,
        rewrite_settings=_input_settings.get(source) != want)
    warnings.extend(warn)
    if item_id is not None:
        _input_settings[source] = want
    return item_id


def _tile_anim_ms():
    """How long the spotlight reflow takes, in ms — Broadcast > Party Scene.
    0 snaps, which a very busy OBS box or a huge party may prefer.

    Parsed through float() on purpose: save_config stores every clamped number
    as one ('700.0'), and int() rejects that outright."""
    try:
        return max(0, min(int(float(appsettingGet('obs_tile_anim_ms', '')
                                    or DEFAULT_TILE_ANIM_MS)), 4000))
    except (TypeError, ValueError):
        return DEFAULT_TILE_ANIM_MS


def _sync_party_scene(featured_id=None):
    """Make OBS match the party: one tile per member, positioned on the grid.

    Tile ORDER is the rotation order, so a player's slot is stable for the
    whole session. Featuring someone spotlights them — their tile doubles and
    the rest shrink around it (see obs_layout) — and tiles that already have a
    known position ease into their new box instead of jumping."""
    import obs_ws
    scene = party_scene_name()
    obs_ws.ensure_scene(scene)

    members = _ordered_party()
    snap = obs_ws.current_state()
    canvas_w = snap.get('base_width') or 1920
    canvas_h = snap.get('base_height') or 1080
    try:
        gutter = int(appsettingGet('obs_tile_gutter', '') or obs_layout.DEFAULT_GUTTER)
    except (TypeError, ValueError):
        gutter = obs_layout.DEFAULT_GUTTER
    featured_idx = None
    if featured_id is not None:
        for i, c in enumerate(members):
            if c.character_id == featured_id:
                featured_idx = i
                break

    # The frame owns the title strip and the info panel, so the tiles get
    # whatever it leaves.
    areas = _frame_areas(canvas_w, canvas_h)
    rects = obs_layout.grid_layout(len(members), canvas_w, canvas_h,
                                   featured=featured_idx, gutter=gutter,
                                   area=areas['tiles'])
    # Every tile RENDERS at the spotlit size whoever currently holds the
    # spotlight — see obs_layout.spotlight_tile_size. The transform scales it
    # down to whatever cell it occupies, so moving the spotlight never resizes
    # a source, and a source that is never resized never blinks.
    render_w, render_h = obs_layout.spotlight_tile_size(
        len(members), canvas_w, canvas_h, gutter, areas['tiles'])

    warnings = []
    placed = []
    moves = []
    anim_ms = _tile_anim_ms()
    presence = _presence()
    overrides = _card_overrides()
    for char, rect in zip(members, rects):
        source = _source_name_for(char)
        url = _tile_url(char, presence, overrides)
        _tile_urls[char.character_id] = url
        item_id = _ensure_input(scene, source, url, render_w, render_h, warnings)
        if item_id is None:
            warnings.append(f'Could not place {char.name} in the scene.')
            continue
        # A tile we have placed before eases from where it is; anything new
        # (or unchanged) is simply put where it belongs.
        target = {k: rect[k] for k in ('x', 'y', 'w', 'h')}
        was = _tile_rects.get(char.character_id)
        if anim_ms and was and was != target:
            moves.append((item_id, was, target))
        else:
            obs_ws.place_item(scene, item_id, rect)
        _tile_rects[char.character_id] = target
        obs_ws.set_item_enabled(scene, item_id, True)
        _upsert_player_map(char.character_id, scene, source, auto_created=1)
        placed.append({'character_id': char.character_id, 'name': char.name,
                       'source': source, 'item_id': item_id,
                       'featured': rect['featured']})

    # Kicked off before the panel/background work below so the move starts
    # while those requests are still going out — it runs on its own thread.
    if moves:
        obs_ws.animate_items(scene, moves, duration_s=anim_ms / 1000.0)

    # Someone who left the party must not leave a stale rect behind: if they
    # come back their tile would ease in from wherever it used to sit.
    live_ids = {p['character_id'] for p in placed}
    for gone in [cid for cid in _tile_rects if cid not in live_ids]:
        _tile_rects.pop(gone, None)

    keep = {p['source'] for p in placed}

    # Title strip and info panel, each in its own box.
    for src, rect, mode, label in (
            (TITLE_SOURCE_NAME, areas['title'], 'title', 'title strip'),
            (PANEL_SOURCE_NAME, areas['panel'], 'info', 'information panel')):
        if rect is None:
            continue        # switched off — _prune_party_scene drops it
        try:
            item_id = _ensure_input(scene, src, panel_url(mode),
                                    int(rect[2]), int(rect[3]), warnings)
            if item_id is not None:
                obs_ws.place_item(scene, item_id, {'x': rect[0], 'y': rect[1],
                                                   'w': rect[2], 'h': rect[3]})
                obs_ws.set_item_enabled(scene, item_id, True)
                keep.add(src)
        except (obs_ws.ObsRejected, obs_ws.ObsUnavailable) as exc:
            warnings.append(f'Could not place the {label} ({exc}).')

    # Art goes in last so its index-0 move lands after every other item is
    # present — otherwise a later insert would push it back up the stack.
    if _place_background(scene, canvas_w, canvas_h, warnings) is not None:
        keep.add(BG_SOURCE_NAME)

    # The battle map no longer shares this scene — it has its own. Drop it if
    # an older build left it here, otherwise it would sit on top of the frame.
    try:
        present = obs_ws.scene_items(scene)
        if MAP_SOURCE_NAME in present:
            obs_ws.remove_item(scene, present[MAP_SOURCE_NAME])
    except (obs_ws.ObsRejected, obs_ws.ObsUnavailable):
        pass

    _prune_party_scene(scene, keep, warnings)
    obs_ws.scene_list(refresh=True)
    return {'scene': scene, 'tiles': placed, 'warnings': warnings,
            'featured_id': featured_id}


def _prune_party_scene(scene, keep_sources, warnings):
    """Drop tiles for players who left the party, so an old member's camera
    doesn't linger on stream."""
    import obs_ws
    try:
        present = obs_ws.scene_items(scene)
    except (obs_ws.ObsRejected, obs_ws.ObsUnavailable):
        return
    for source, item_id in present.items():
        if source in keep_sources:
            continue
        # Only remove tiles WE created — never touch the DM's own overlays,
        # lower thirds or backgrounds that share this scene.
        if not source.startswith(_MANAGED_PREFIXES):
            continue
        try:
            obs_ws.remove_item(scene, item_id)
        except (obs_ws.ObsRejected, obs_ws.ObsUnavailable) as exc:
            warnings.append(f'Could not remove the old tile "{source}" ({exc}).')


def _ordered_party(include_offstage=False):
    """Everyone with a tile, in turn order: saved order first, then anyone
    new, so adding a character never renumbers the rest.

    The DM rides along as a normal entry — they take turns narrating too —
    and lands at the front until the DM reorders themselves elsewhere.

    Benched players are left out, which is what keeps them off the grid AND
    out of the rotation, so the number keys count the tiles actually on
    screen. include_offstage=True is for the Broadcast page, which has to list
    them or there would be no way to bring anyone back."""
    party = {c.character_id: c for c in _active_party()}
    if dm_tile_enabled():
        party[DM_TILE_ID] = dm_tile()
    if not include_offstage:
        for benched in offstage_ids():
            party.pop(benched, None)
    ordered = []
    rows = (tblObsSceneMap.query
            .filter_by(entity_type='player')
            .order_by(tblObsSceneMap.sort_order, tblObsSceneMap.obs_map_id)
            .all())
    for row in rows:
        if row.entity_id in party:
            ordered.append(party.pop(row.entity_id))
    # A DM with no saved position leads; new players follow by name.
    dm = party.pop(DM_TILE_ID, None)
    rest = sorted(party.values(), key=lambda c: c.name.lower())
    if dm is not None:
        ordered.insert(0, dm)
    ordered.extend(rest)
    return ordered


def _scene_name_for(char):
    clean = re.sub(r'[\x00-\x1f]', '', char.name or '').strip() or f'Player {char.character_id}'
    prefix = 'DM - ' if char.character_id == DM_TILE_ID else 'Player - '
    return f'{prefix}{clean}'[:200]


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


@obs_bp.route('/feed/dm', methods=['GET', 'POST'])
@login_required
@dm_required
def dm_feed():
    """The DM's own camera link. Same self-service page as a player's, but
    the identity lives in settings rather than on a character."""
    if request.method == 'POST':
        action = request.form.get('action', 'save')
        if action == 'regenerate':
            appsettingSet('obs_dm_stream_id', _new_stream_id())
            appsettingSet('obs_dm_feed_url', '')
            flash('New camera link generated — the old one no longer works.')
        else:
            try:
                appsettingSet('obs_dm_feed_url',
                              _normalize_feed_url(request.form.get('video_feed_url')))
            except ValueError as exc:
                flash(str(exc))
                return redirect(url_for('obs_bp.dm_feed'))
            if not (appsettingGet('obs_dm_feed_url', '')
                    or appsettingGet('obs_dm_stream_id', '')):
                appsettingSet('obs_dm_stream_id', _new_stream_id())
            flash('Camera settings saved.')
        refresh_tiles()
        return redirect(url_for('obs_bp.dm_feed'))

    if not (appsettingGet('obs_dm_stream_id', '')
            or appsettingGet('obs_dm_feed_url', '')):
        appsettingSet('obs_dm_stream_id', _new_stream_id())
    tile = dm_tile()
    return render_template('ttrpg/obs_my_feed.html', char=tile,
                           push_url=tile.video_push_url(),
                           view_url=tile.video_view_url(),
                           qr_svg=_qr_svg(tile.video_push_url()),
                           is_dm=True, is_dm_tile=True,
                           save_url=url_for('obs_bp.dm_feed'))


def portal_login_url():
    """Where a remote player logs in, or '' when there is no relay.

    The portal is served at the ROOT of the relay (main.py mounts it last, so
    API routes win), which is why this is just relay_url. A remote player
    cannot reach this ScenePlay at all, so the camera page is useless to
    them — the portal link is the one thing worth sending.

    Gated on the URL being configured, NOT on relay_enabled: the GM often
    sets the table up before switching the relay on, and that is exactly when
    they want to send people the link."""
    return (appsettingGet('relay_url', '') or '').strip().rstrip('/')


@obs_bp.route('/feed/<int:character_id>')
@login_required
def my_feed(character_id):
    char = _own_character(character_id)
    # Mint the id on first visit so the page always has something to show.
    if not char.video_stream_id and not char.video_feed_url:
        char.video_stream_id = _new_stream_id()
        db.session.commit()
    push_url = char.video_push_url()
    portal = portal_login_url()
    return render_template('ttrpg/obs_my_feed.html',
                           char=char,
                           push_url=push_url,
                           view_url=char.video_view_url(),
                           qr_svg=_qr_svg(push_url),
                           portal_url=portal,
                           portal_qr=_qr_svg(portal) if portal else '',
                           player_username=(char.user.username
                                            if char.user else ''),
                           is_dm=current_user.is_dm(), is_dm_tile=False,
                           save_url=url_for('obs_bp.save_feed',
                                            character_id=character_id))


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
    # ...and the relay, or a regenerated link would leave the portal handing
    # the player a dead one with nothing to say it had changed.
    _push_feeds_to_relay()
    return redirect(url_for('obs_bp.my_feed', character_id=character_id))


def _push_feeds_to_relay():
    """Re-send every camera link to the relay.

    Lazily imported and deliberately swallowing failures: the relay is
    optional, often disabled, and a player saving their camera settings must
    not see an error because a remote service is down."""
    try:
        import relay_broadcaster
        relay_broadcaster.push_character_feeds()
    except Exception as exc:      # noqa: BLE001 - never block the save
        current_app.logger.info('feed push to the relay skipped: %s', exc)


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


# ── player card (the tile for someone with no camera) ────────────────────────
# OBS's browser source has no ScenePlay login, so the card is gated by a
# per-character token instead — the same capability model as a camera link.
# Derived from the app secret, so it needs no storage and rotating the secret
# revokes every card at once.

def _card_token(character_id):
    import hashlib
    import hmac
    key = (current_app.secret_key or '').encode() or b'sceneplay'
    return hmac.new(key, f'obs-card:{character_id}'.encode(),
                    hashlib.sha256).hexdigest()[:32]


DEFAULT_CARD_PORT = 8086          # the port ws.py serves ScenePlay on


def _card_base():
    """Where OBS should fetch cards from.

    Must be ABSOLUTE — a browser source has no page to be relative to — and
    built without url_for, which needs a request context this can't rely on
    (the auto-return timer calls it from a plain thread). Auto-filled from the
    DM's own address when they open the Broadcast page; override it when OBS
    runs on a different machine from ScenePlay."""
    base = (appsettingGet('obs_card_base', '') or '').strip()
    return base.rstrip('/') if base else f'http://127.0.0.1:{DEFAULT_CARD_PORT}'


def card_url(character_id):
    # Flask's <int:> converter never matches a negative number, so the DM's
    # card gets its own path rather than /card/-1.
    leaf = 'dm' if character_id == DM_TILE_ID else str(character_id)
    return (f'{_card_base()}{obs_bp.url_prefix}/card/{leaf}'
            f'?t={_card_token(character_id)}')


@obs_bp.route('/card/dm')
def dm_card():
    """The DM's tile when they have no camera. Same token gate as a player
    card; a separate path because <int:> never matches a negative id."""
    import hmac
    if not hmac.compare_digest(request.args.get('t', ''), _card_token(DM_TILE_ID)):
        abort(403)
    tile = dm_tile()
    return render_template('ttrpg/obs_card.html', char=tile, conditions=[],
                           is_dm=True, poll_s=card_poll_s(),
                           poll_url=url_for('obs_bp.dm_card_state',
                                            t=request.args.get('t', '')))


@obs_bp.route('/card/dm/state')
def dm_card_state():
    import hmac
    if not hmac.compare_digest(request.args.get('t', ''), _card_token(DM_TILE_ID)):
        abort(403)
    tile = dm_tile()
    return jsonify({'name': tile.name, 'hp_current': 0, 'hp_max': 0,
                    'hp_pct': 0, 'ac': 0, 'conditions': [],
                    'player': dm_player_name(), 'is_dm': True})


@obs_bp.route('/tile/dm')
def dm_tile_view():
    """The DM's camera with their name over it. Separate path for the same
    reason /card/dm is: <int:> will not match the DM's negative id."""
    import hmac
    token = request.args.get('t', '')
    if not hmac.compare_digest(token, _card_token(DM_TILE_ID)):
        abort(403)
    tile = dm_tile()
    return render_template(
        'ttrpg/obs_tile.html', char=tile,
        player=dm_player_name(), portrait_url='',
        feed_url=tile.video_view_url(),
        conditions=[], is_dm=True, poll_s=card_poll_s(),
        poll_url=url_for('obs_bp.dm_card_state', t=token))


@obs_bp.route('/tile/<int:character_id>')
def player_tile(character_id):
    """A player's camera with their character laid over it.

    The feed is FRAMED rather than being the source itself, so one browser
    source carries both the video and the character strip. Two stacked
    sources would have meant a second CEF instance per player and two
    transforms to keep aligned as the grid resizes.

    Framing is only safe for the VIEW url: it is playback, needing no camera
    permission. The PUSH url must never be framed — camera delegation from a
    LAN http:// parent is blocked, which is why the player's own page links
    out to it instead."""
    import hmac
    token = request.args.get('t', '')
    if not hmac.compare_digest(token, _card_token(character_id)):
        abort(403)
    char = db.session.get(tblCharacters, character_id)
    if not char:
        abort(404)
    return render_template(
        'ttrpg/obs_tile.html', char=char,
        player=player_name_for(char),
        portrait_url=(url_for('static',
                              filename=f'uploads/portraits/{char.portrait_path}')
                      if char.portrait_path else ''),
        feed_url=char.video_view_url(),
        conditions=[c.condition_name for c in char.conditions] if char.conditions else [],
        poll_s=card_poll_s(),
        poll_url=url_for('obs_bp.card_state', character_id=character_id, t=token))


@obs_bp.route('/card/<int:character_id>')
def player_card(character_id):
    """Transparent stat card for OBS. No login: OBS can't hold a session, so
    the URL carries a token. compare_digest to keep it constant-time."""
    import hmac
    token = request.args.get('t', '')
    if not hmac.compare_digest(token, _card_token(character_id)):
        abort(403)
    char = db.session.get(tblCharacters, character_id)
    if not char:
        abort(404)
    conditions = [c.condition_name for c in char.conditions] if char.conditions else []
    return render_template('ttrpg/obs_card.html', char=char,
                           conditions=conditions, is_dm=False,
                           player=player_name_for(char),
                           poll_s=card_poll_s(),
                           poll_url=url_for('obs_bp.card_state',
                                            character_id=character_id,
                                            t=token))


@obs_bp.route('/card/<int:character_id>/state')
def card_state(character_id):
    """Live values for the card — it polls this so HP/conditions track play
    without the DM touching anything."""
    import hmac
    if not hmac.compare_digest(request.args.get('t', ''), _card_token(character_id)):
        abort(403)
    char = db.session.get(tblCharacters, character_id)
    if not char:
        abort(404)
    return jsonify({
        'name': char.name,
        'player': player_name_for(char),
        'hp_current': char.hp_current, 'hp_max': char.hp_max,
        'hp_pct': char.hp_pct(), 'ac': char.ac,
        'conditions': [c.condition_name for c in char.conditions] if char.conditions else [],
    })


# ── the shared battle map ─────────────────────────────────────────────────────
# A chrome-free render of the live map for OBS: no nav bar, no sidebar, no
# browser furniture — so it can be a browser SOURCE rather than a window or
# display capture. Token-gated like the player cards.
#
# Visibility is resolved SERVER-SIDE. The map is drawn through the eyes of
# whoever moved last, and anything their character cannot see never reaches
# the browser at all — a hidden monster must not be sitting in the page source
# of something being broadcast.

MAP_TOKEN_KEY = 'obs-map'
TITLE_DIR = os.path.join('static', 'uploads', 'obs')
TITLE_EXT = {'png', 'jpg', 'jpeg', 'webp', 'gif'}


def _map_token():
    import hashlib
    import hmac
    key = (current_app.secret_key or '').encode() or b'sceneplay'
    return hmac.new(key, MAP_TOKEN_KEY.encode(), hashlib.sha256).hexdigest()[:32]


def map_url():
    return f'{_card_base()}{obs_bp.url_prefix}/map?t={_map_token()}'


def _check_map_token():
    import hmac
    if not hmac.compare_digest(request.args.get('t', ''), _map_token()):
        abort(403)


def _fog_rects(effects):
    """Cloud effects as (x1, y1, x2, y2) cell rects — the same geometry the
    2D page and the 3D viewer use."""
    out = []
    for e in effects:
        if e.get('shape') != 'cloud':
            continue
        w = max(1.0, (e.get('size_ft') or 5) / 5.0)
        h = e.get('angle') if (e.get('angle') or 0) > 0 else w
        x1, y1 = e.get('anchor_x') or 0, e.get('anchor_y') or 0
        out.append((x1, y1, x1 + w, y1 + h))
    return out


def _hidden_by_fog(token, fog):
    span = max(1, token.get('size_squares') or 1)
    cx = (token.get('col') or 0) + span / 2.0
    cy = (token.get('row') or 0) + span / 2.0
    return any(x1 <= cx < x2 and y1 <= cy < y2 for x1, y1, x2, y2 in fog)


# One source per box. The title input is shared by the Party and Map scenes,
# and the Info panel and the Map's Dice feed are placed with the SAME rect —
# which is what makes "identical in both scenes" structural instead of two
# separate calculations that have to agree.
PANEL_SOURCE_NAME = 'ScenePlay Info'
TITLE_SOURCE_NAME = 'ScenePlay Title'
BG_SOURCE_NAME = 'ScenePlay Background'
DICE_SOURCE_NAME = 'ScenePlay Dice'
ROLL_LIMIT = 25


def _place_background(scene, canvas_w, canvas_h, warnings):
    """Put the art at the very back of `scene`.

    One input shared by every ScenePlay scene rather than a copy each:
    obs-websocket lets a single input live in several scenes with independent
    transforms, so changing the image updates all of them at once and the
    streaming box pays for one browser source instead of three."""
    import obs_ws
    try:
        # Through _ensure_input: this runs on every party sync, and rewriting
        # the art's settings each time re-renders it behind the cameras.
        item_id = _ensure_input(scene, BG_SOURCE_NAME, panel_url('bg'),
                                canvas_w, canvas_h, warnings)
        if item_id is None:
            return None
        obs_ws.place_item(scene, item_id,
                          {'x': 0, 'y': 0, 'w': canvas_w, 'h': canvas_h})
        obs_ws.set_item_enabled(scene, item_id, True)
        try:
            # Index 0 is the BOTTOM of the stack — anything else and the art
            # covers the cameras it is supposed to sit behind.
            obs_ws.set_item_index(scene, item_id, 0)
        except obs_ws.ObsRejected as exc:
            warnings.append(f'Could not send the background to the back ({exc}).')
        return item_id
    except (obs_ws.ObsRejected, obs_ws.ObsUnavailable) as exc:
        warnings.append(f'Could not place the background ({exc}).')
        return None


@obs_bp.route('/image/<slot>', methods=['POST'])
@login_required
@dm_required
def upload_image(slot):
    """Upload (or clear) one of the broadcast images.

    One handler for all of them. There used to be three near-identical ones,
    which is how the controls for them ended up in three different places on
    the page — the UI drifted because the code had."""
    if slot not in IMAGE_SLOTS:
        abort(404)
    setting, stem, label = IMAGE_SLOTS[slot]
    if request.form.get('clear'):
        appsettingSet(setting, '')
        flash(f'{label.split(chr(8212))[0].strip()} cleared.')
        return redirect(url_for('obs_bp.broadcast'))
    f = request.files.get('image')
    if not f or not f.filename:
        flash('No image chosen.')
        return redirect(url_for('obs_bp.broadcast'))
    ext = f.filename.rsplit('.', 1)[-1].lower()
    if ext not in TITLE_EXT:
        flash('Use a PNG, JPG, WEBP or GIF.')
        return redirect(url_for('obs_bp.broadcast'))
    os.makedirs(BG_DIR, exist_ok=True)
    # Downscale before saving, like every other image intake (portraits,
    # tokens, map art all go through the same helper). These render at most
    # 1920px wide on the canvas, so a 9MB AI generation is pure waste — disk,
    # LAN bandwidth, and a decode stall in OBS's browser source every reload.
    # Animated GIFs and Pillow failures fall through with the original bytes.
    from relay_broadcaster import _downscale_image
    raw = f.read()
    raw, ext = _downscale_image(raw, ext, max_dim=1920)
    # A stable name per slot: the browser sources cache by URL, so reusing it
    # means a re-upload replaces the art everywhere instead of leaving the old
    # file referenced.
    name = f'{stem}.{ext}'
    with open(os.path.join(BG_DIR, name), 'wb') as out:
        out.write(raw)
    for other in TITLE_EXT:                 # drop a previous different format
        old = os.path.join(BG_DIR, f'{stem}.{other}')
        if other != ext and os.path.exists(old):
            try:
                os.remove(old)
            except OSError:
                pass
    appsettingSet(setting, name)
    flash('Image updated. Reload the affected source in OBS to see it.')
    return redirect(url_for('obs_bp.broadcast'))


PANEL_MODES = ('bg', 'title', 'info', 'dice', 'pre', 'intermission', 'post')


@obs_bp.route('/panel')
def panel_view():
    """One page, three modes — see the template header."""
    import hmac
    if not hmac.compare_digest(request.args.get('t', ''), _panel_token()):
        abort(403)
    mode = (request.args.get('mode') or 'info').strip().lower()
    return render_template('ttrpg/obs_panel.html',
                           mode=mode if mode in PANEL_MODES else 'info',
                           # Same table that defines the show scenes, so a new
                           # card can never be a scene the page won't paint.
                           card_modes=sorted(SHOW_SOURCE),
                           state_url=url_for('obs_bp.panel_state',
                                             t=_panel_token()),
                           poll_s=panel_poll_s())


def panel_poll_s():
    """Faster than the stat cards: a roll landing on stream 10s after it was
    made has already stopped being news at the table."""
    try:
        return min(max(float((appsettingGet('obs_panel_poll_s', '') or '').strip()
                             or 4), 1), 60)
    except (TypeError, ValueError):
        return 4.0


def _info_lines():
    raw = appsettingGet('obs_info_text', '') or ''
    return [ln.rstrip() for ln in raw.splitlines() if ln.strip()]


def _recent_rolls(limit=ROLL_LIMIT):
    """Oldest first.

    The panel shows the newest roll on the TOP line and prepends each arrival,
    so feeding it oldest-first is what leaves them in the right order — each
    new row pushes the previous one down."""
    import json as _json
    from models.ttrpg import tblDiceRolls
    rows = (tblDiceRolls.query.order_by(tblDiceRolls.roll_id.desc())
            .limit(limit).all())
    out = []
    for r in reversed(rows):
        try:
            dice = _json.loads(r.dice_json or '[]')
        except (TypeError, ValueError):
            dice = []
        # Crit/fumble only mean anything on a single d20: flagging the natural
        # 20 inside a handful of d6 damage dice would light up constantly.
        nat = dice[0] if len(dice) == 1 else None
        d20 = 'd20' in (r.expression or '').lower()
        out.append({
            'id': r.roll_id,
            'who': r.char_name or '',
            'label': r.label or '',
            'expression': r.expression or '',
            'total': r.total,
            'crit': bool(d20 and nat == 20),
            'fumble': bool(d20 and nat == 1),
        })
    return out


@obs_bp.route('/panel/state')
def panel_state():
    import hmac
    if not hmac.compare_digest(request.args.get('t', ''), _panel_token()):
        abort(403)
    snap = {}
    try:
        import obs_ws
        snap = obs_ws.current_state()
    except Exception:      # noqa: BLE001 - the panel must render without OBS
        snap = {}
    canvas_w = snap.get('base_width') or 1920
    canvas_h = snap.get('base_height') or 1080
    areas = _frame_areas(canvas_w, canvas_h)

    sess = tblSessions.query.filter_by(status='active').first()
    title = (appsettingGet('obs_panel_title', '') or '').strip()
    if not title:
        # Same derivation the map's idle card uses, so the two agree.
        tp = _title_payload(sess)
        title = tp['campaign'] or tp['session'] or 'ScenePlay'
    bg = (appsettingGet('obs_party_bg', '') or '').strip()

    turn = ''
    fid = featured_id()
    if fid is not None and fid != DM_TILE_ID:
        ch = db.session.get(tblCharacters, fid)
        if ch:
            turn = ch.name
    elif fid == DM_TILE_ID:
        turn = dm_tile().name

    lines = _info_lines()
    return jsonify({
        'canvas_w': canvas_w, 'canvas_h': canvas_h,
        'title_rect': areas['title'], 'panel_rect': areas['panel'],
        'bg_url': (f'{_card_base()}/static/uploads/obs/{bg}' if bg else ''),
        'title': title,
        'turn': turn,
        'info_lines': lines,
        # Always sent now: the party panel prefers notes over dice, but the
        # dice source on the battle map wants them regardless of notes.
        'rolls': _recent_rolls(),
        # Where a dice-only source sits. Computed with the panel forced on, so
        # turning the party panel off doesn't leave the map's dice homeless.
        'dice_rect': obs_layout.frame_areas(canvas_w, canvas_h, panel_side(),
                                            panel_fraction(), title_height(),
                                            True)['panel'],
        'pre': show_cfg('pre'),
        'intermission': show_cfg('intermission'),
        'post': show_cfg('post'),
        'image_fraction': SHOW_IMAGE_FRACTION,
    })


@obs_bp.route('/map')
def map_view():
    """The map source itself. Static URL: whose eyes it uses is decided by the
    state poll, so giving someone the turn never reloads the browser source."""
    _check_map_token()
    return render_template(
        'ttrpg/obs_map.html',
        state_url=url_for('obs_bp.map_state', t=_map_token()),
        floorplan_url=url_for('obs_bp.map_floorplan', t=_map_token()),
        three_url=url_for('static', filename='scripts/three.min.js'),
        bm3d_url=url_for('static', filename='scripts/battlemap3d.js'))


@obs_bp.route('/map/state')
def map_state():
    """Everything the map source draws, already filtered for what the audience
    is allowed to see."""
    _check_map_token()
    from models.ttrpg import tblBattleMaps
    from flask import url_for as _url_for

    sess = tblSessions.query.filter_by(status='active').first()
    bm = (tblBattleMaps.query.filter_by(session_id=sess.session_id, is_active=1).first()
          if sess else None)
    if bm is None or not bm.bg_image:
        # Nothing live: the source shows the title card rather than a stale
        # map or an empty black rectangle.
        return jsonify({'live': False, 'title': _title_payload(sess)})

    tokens, effects = _map_payload(bm)
    fog = _fog_rects(effects)
    # Fog is opaque for the audience and anything inside it is dropped — the
    # broadcast never carries what the party has not uncovered.
    visible = [t for t in tokens if not _hidden_by_fog(t, fog)]

    # Resolved against the VISIBLE list on purpose: the 3D view stands in this
    # token, so it has to be one we actually sent. A featured player who is
    # off the map — or inside fog — yields nothing, and the source falls back
    # to the 2D render rather than adopting a viewpoint that isn't there.
    # The view follows whoever moved LAST, so the shot goes where the action
    # is rather than staying with whoever the DM clicked most recently. The
    # featured player is the fallback, for a map where nothing has moved yet.
    through = None
    pinned = viewed_character_id()
    if pinned is not None:
        through = next((t for t in visible if t['entity_type'] == 'player'
                        and t['entity_id'] == pinned), None)
    if through is None:
        last_id = _last_moved_token_id(bm)
        if last_id is not None:
            through = next((t for t in visible if t['token_id'] == last_id), None)
    featured = featured_id()
    if through is None and featured is not None and featured != DM_TILE_ID:
        through = next((t for t in visible
                        if t['entity_type'] == 'player' and t['entity_id'] == featured), None)
    return jsonify({
        'live': True,
        'bg_url': _url_for('static', filename=f'uploads/battlemaps/{bm.bg_image}'),
        'is_video': bm.bg_image.rsplit('.', 1)[-1].lower() in ('mp4', 'webm', 'ogv'),
        'cols': bm.grid_cols, 'rows': bm.grid_rows,
        'tokens': visible,
        'effects': [e for e in effects if e.get('shape') != 'cloud'],
        'fog': [{'x1': r[0], 'y1': r[1], 'x2': r[2], 'y2': r[3]} for r in fog],
        'through': (through or {}).get('name', ''),
        'through_token_id': (through or {}).get('token_id'),
        # Only set when the DM pinned someone: it tells the 2D render to hold
        # a close-up on that character instead of framing the whole party.
        'focus_token_id': ((through or {}).get('token_id')
                           if pinned is not None and through else None),
        'map_name': bm.name,
        'zoom': _zoom_cfg(),
        # The effective mode: a pin overrides the configured one for as long
        # as it is held. The Broadcast page and the sidebar button keep
        # reading map_mode(), so what the DM chose still shows as chosen.
        'mode': effective_map_mode(bm, pinned is not None and through is not None),
        # Exactly the rule the map page uses for its own 3D button
        # (routes/battlemap.py: bm3d_available) — geometry AND art. Without
        # both, 3D is not available for this map and the source stays 2D.
        'three_d_ready': _three_d_available(bm),
        'floorplan_version': _map_floorplan_version(bm.map_id),
        'doors': _map_door_states(bm.map_id),
        'map_id': bm.map_id,
        # feet -> squares for the look-around range; a map can redefine what a
        # square is worth.
        'movement_scale': bm.movement_scale or 1.0,
    })


def _three_d_available(bm):
    """Mirror of bm3d_available on the battle map page: 3D needs a floorplan
    to build walls from AND background art to texture them with."""
    return bool(_map_floorplan_version(bm.map_id) and bm.bg_image)


def card_poll_s():
    """How often a stat card re-checks HP and conditions, in seconds.

    Every card in the party scene is its own browser source, so this is
    multiplied by the size of the party — at the old fixed 3s an eight-player
    table meant a request every 375ms all session. Cards show HP and
    conditions, which move at the pace of a turn, not a frame."""
    try:
        return min(max(float((appsettingGet('obs_card_poll_s', '') or '').strip()
                             or CARD_POLL_DEFAULT), 2), 120)
    except (TypeError, ValueError):
        return CARD_POLL_DEFAULT


def effective_map_mode(bm, pinned):
    """What the map source should actually render right now.

    Equal to map_mode() unless the DM has pinned the view to a character.
    A pin overrides AUTO — which would otherwise cut back to the flat map
    part-way through — but never overrides an explicit 2D: someone who
    deliberately chose the top-down view should get a close-up of the
    character, not be argued with. Explicit 3D and auto both give 3D where
    the map can render it."""
    if not pinned:
        return map_mode()
    if map_mode() == '2d':
        return '2d'
    return '3d' if _three_d_available(bm) else '2d'


def map_mode():
    """'auto' | '2d' | '3d'.

    'auto' is the default because it is the only one that needs no attention
    during play: the source sits on the 2D map and cuts to the featured
    player's 3D view only when they actually move, then cuts back. '2d' and
    '3d' pin it for a DM who wants to hold one shot."""
    mode = (appsettingGet('obs_map_mode', 'auto') or 'auto').strip().lower()
    return mode if mode in MAP_MODES else 'auto'


def _map_floorplan_version(map_id):
    from models.ttrpg import tblBattleMapFloorplans
    fp = tblBattleMapFloorplans.query.filter_by(map_id=map_id).first()
    return fp.version if fp else None


def _map_door_states(map_id):
    from models.ttrpg import tblBattleMapDoors
    return {d.door_key: d.is_open
            for d in tblBattleMapDoors.query.filter_by(map_id=map_id).all()}


@obs_bp.route('/map/floorplan')
def map_floorplan():
    """Wall geometry for the 3D branch, in the shape BM3D's floorplanUrl
    expects. Fetched only when the version changes, never on the 2 s poll."""
    _check_map_token()
    from models.ttrpg import tblBattleMapFloorplans
    try:
        map_id = int(request.args.get('map_id') or 0)
    except (TypeError, ValueError):
        map_id = 0
    fp = tblBattleMapFloorplans.query.filter_by(map_id=map_id).first()
    if not fp:
        return jsonify({'ok': True, 'version': None, 'floorplan': None})
    import json as _json
    return jsonify({'ok': True, 'version': fp.version,
                    'floorplan': _json.loads(fp.json_data)})


def _zoom_cfg():
    """Action-camera settings, sent with the state so changing them takes
    effect without reloading the browser source."""
    def _num(name, default, lo, hi):
        try:
            return min(max(float(appsettingGet(name, '') or default), lo), hi)
        except (TypeError, ValueError):
            return default
    return {
        'on': (appsettingGet('obs_map_zoom', '1') or '1') == '1',
        'max': _num('obs_map_zoom_max', 2.2, 1.0, 6.0),
        'hold_s': _num('obs_map_zoom_hold_s', 6, 1, 120),
    }


def viewed_character_id():
    """Character the DM pinned the map view to, or None.

    Beats the follow-the-last-mover rule: an explicit click is a shot call and
    must not be stolen a moment later by whoever happens to shuffle a token.
    Cleared by the group shot, which is how you hand the camera back."""
    raw = (appsettingGet('obs_view_char', '') or '').strip()
    try:
        return int(raw) or None
    except (TypeError, ValueError):
        return None


def _set_viewed_character(character_id):
    appsettingSet('obs_view_char', str(character_id or ''))


def _last_moved_token_id(bm):
    """token_id of the player token moved most recently, or None.

    Reads tblBattleMapTokens.updated_at, which BOTH the table's own move
    endpoint and the relay's portal moves already stamp — so a move made from
    a handheld counts exactly like one made at the table, with no extra
    bookkeeping on either path.

    A timestamp shared by more than one token is deliberately not treated as a
    move: activating a map stamps every token with one activation time, and a
    grid resize stamps each token it clamps. Only a uniquely-latest stamp is
    someone actually moving, which stops the camera adopting an arbitrary
    viewpoint the moment a map goes live.

    Monsters are excluded. "Character" here means a PC, and standing in a
    monster's shoes would put the camera where the DM has hidden something —
    the audience would read its position off the viewpoint even though the
    token itself is filtered out of the payload."""
    stamps = {}
    for t in bm.tokens:
        if t.entity_type != 'player':
            continue
        ts = (t.updated_at or '').strip()
        if ts:
            stamps.setdefault(ts, []).append(t.token_id)
    if not stamps:
        return None
    newest = stamps[max(stamps)]
    return newest[0] if len(newest) == 1 else None


def _map_payload(bm):
    """Reuse the battle map's own state builder so the broadcast render can
    never drift from what the table sees."""
    from routes.battlemap import _fetch_token_entities, _monster_stats, _size_squares, _monster_img_url
    from flask import url_for as _url_for
    monsters, chars = _fetch_token_entities(bm.tokens)
    tokens = []
    for t in bm.tokens:
        if t.entity_type == 'monster':
            sm = monsters.get(t.entity_id)
            if not sm or not sm.is_alive:
                continue
            stats = _monster_stats(sm)
            tokens.append({'token_id': t.token_id, 'is_alive': 1,
                           'entity_type': 'monster', 'entity_id': t.entity_id,
                           'name': sm.display_name, 'col': t.col, 'row': t.row,
                           'hp_pct': sm.hp_pct(),
                           'size_squares': _size_squares(sm.template.size if sm.template else ''),
                           'image_url': _monster_img_url(stats['image']),
                           'color': '#cc3333'})
        else:
            char = chars.get(t.entity_id)
            if not char:
                continue
            img = (_url_for('static', filename=f'uploads/portraits/{char.portrait_path}')
                   if char.portrait_path else '')
            tokens.append({'token_id': t.token_id, 'is_alive': 1,
                           'entity_type': 'player', 'entity_id': t.entity_id,
                           'name': char.name, 'col': t.col, 'row': t.row,
                           'hp_pct': char.hp_pct(), 'size_squares': 1,
                           'image_url': img, 'color': '#4a9eff'})
    effects = [{'shape': e.shape, 'label': e.label, 'anchor_x': e.anchor_x,
                'anchor_y': e.anchor_y, 'size_ft': e.size_ft, 'angle': e.angle,
                'fill_color': e.fill_color, 'fill_opacity': e.fill_opacity,
                'border_color': e.border_color} for e in bm.effects]
    return tokens, effects


def _title_payload(sess):
    from flask import url_for as _url_for
    img = (appsettingGet('obs_title_image', '') or '').strip()
    campaign = ''
    if sess and sess.campaign_id:
        from models.campaigns import tblcampaigns
        camp = db.session.get(tblcampaigns, sess.campaign_id)
        campaign = camp.campaign_name if camp else ''
    return {
        'image_url': _url_for('static', filename=f'uploads/obs/{img}') if img else '',
        'campaign': campaign,
        'session': (sess.title if sess else ''),
    }


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
