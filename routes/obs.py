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
import time
import uuid
from datetime import datetime
from urllib.parse import unquote, urlsplit

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
        'panel_notes':   panel_note_rows(),
        'yt':            _yt_cfg(),
        'party_bg':      art_setting('obs_party_bg'),
        'portal_url':    portal_login_url(),
        'feed_noaudio':  (appsettingGet('obs_feed_noaudio', '0') or '0'),
        'dm_audio':      (appsettingGet('obs_dm_audio', '0') or '0'),
        'feed_monitor':  (appsettingGet('obs_feed_monitor', '0') or '0'),
        'vdo_room':      table_room(),
        'room_audio_only': (appsettingGet('obs_room_audio_only', '1') or '1'),
        'room_videobitrate': _room_bitrate_str(),
        'room_join_url': (dm_tile().video_push_url() if table_room() else ''),
        'accent':        theme_accent(),
        'base':          theme_base(),
        'base2':         theme_base2(),
        'base_dir':      theme_base_dir(),
        'bezel':         bezel_shape(),
        'bezel_shapes':  BEZEL_SHAPES,
        'plate':         theme_plate(),
        'plate2':        theme_plate2(),
        'plate_dir':     theme_plate_dir(),
        'card_design':   card_design(),
        'card_designs':  CARD_DESIGNS,
        'tile_design':   tile_design(),
        'tile_designs':  TILE_DESIGNS,
        'dm_icon':       dm_icon(),
        'dm_icons':      DM_ICONS,
        'dm_title':      dm_title(),
        'theme_own':     _theme_session_own(),
        'music_capture': ('1' if music_capture_on() else '0'),
        'music_device':  music_device_id(),
        'music_transport': (appsettingGet('obs_music_transport', 'auto')
                            or 'auto'),
        'music_resolved': music_transport(),
        # Whether the path in use was CHOSEN or worked out. A stale manual
        # choice looks identical to a correct automatic one on the page, and
        # it silently survives moving OBS back to this machine — which is how
        # a local rig ended up waiting on a vdo.ninja tab nobody had opened.
        'music_forced': ((appsettingGet('obs_music_transport', 'auto')
                          or 'auto') != 'auto'),
        'music_label':   music_device_label(),
        'music_push':    music_push_url(),
        # The cable half of the feed path — Windows only, where there is no
        # sink for mpv to play into and nothing for the push tab to capture.
        'music_cable':   music_cable_platform(),
        'music_out':     music_output_device(),
        'music_outs':    music_output_options(),
        'music_label_opts': music_label_options(),
        'obs_local':     obs_is_local(),
        'rig':           rig_summary(),
        'dm_mic_label':  (appsettingGet('obs_dm_mic_label', '') or ''),
        'dm_mic_hint':   (appsettingGet('obs_dm_mic_label', '')
                          or 'your mic\'s name'),
        'card_base':     _card_base(),
        'card_base_lan': lan_base(),
        'card_base_loopback': is_loopback_base(_card_base()),
        'card_base_suggested': suggested_card_base(),
        'card_base_stale': card_base_stale(),
        'panel_poll':    ('%g' % panel_poll_s()),
        'dice_autohide': ('1' if dice_autohide_on() else '0'),
        'pre':           show_cfg('pre'),
        'intermission':  show_cfg('intermission'),
        'post':          show_cfg('post'),
        'images':        image_slots(),
        'title_positions': TITLE_POSITIONS,
        'title_image':   art_setting('obs_title_image'),
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
        """The DM's camera link, with their microphone pinned if they said
        which one.

        Worth pinning on the machine that also plays the music: a bare label
        match can land on the wrong device. A typical box lists the same name
        twice — once as the microphone and once as "Monitor of ..." the
        speakers — and picking the monitor would put the music and every
        player's voice into the DM's own microphone channel."""
        from models.ttrpg import _vdo_url
        from urllib.parse import quote
        if self.video_feed_url or not self.video_stream_id:
            return ''
        url = _vdo_url('push', self.video_stream_id)
        mic = (appsettingGet('obs_dm_mic_label', '') or '').strip()
        if mic and 'audiodevice=' not in url:
            url += '&audiodevice=' + quote(mic, safe='')
        return url

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
    """Who runs the table, for the DM tile's second line. Display name ONLY —
    the login is an account credential and stays off the stream. Empty when
    no display name is set; the tile just leaves the line blank."""
    from models.user import tblUsers
    row = tblUsers.query.filter_by(role='dm', active=1).first()
    name = (getattr(row, 'display_name', '') or '').strip() if row else ''
    # dm_name() already uses the display name as the tile's TITLE; repeating
    # it right underneath says nothing new.
    return '' if name == dm_name() else name


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
    muted_ids = _muted_ids()
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
            'muted': char.character_id in muted_ids,
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


# ── auto cameras: swap on what the tile actually SHOWS ───────────────────────
# Relay presence only covers portal players. This watches the pixels instead:
# each pass screenshots every camera source small and cheap, and a feed that
# renders black gets that player's stat card until light comes back. Two dark
# passes to swap away (a slow WebRTC reconnect must not flap the tile), one
# lit pass to swap back (the audience should see a returning face fast).
_cam_dark_votes = {}             # character_id -> consecutive dark passes
_auto_dark_ids = set()           # currently swapped to card by the watcher
_cam_timer = None
AUTO_CAM_DARK_PASSES = 2
AUTO_CAM_LUMA = 10               # 0-255 mean; a live face is way above this
# The watch runs on its own timer, not the 20 s feed watch, and paces itself:
# FAST while any feed is dark or has a dark vote pending (a returning face
# should show within a couple of seconds; a real drop should be covered in
# ~2×FAST, not ~2×20 s), IDLE when every camera is lit, and OFF is just a
# setting read every few seconds so switching it on takes effect promptly.
# The per-camera cost is one 96×54 screenshot and a histogram — around a
# millisecond of OBS render time — so even FAST with a full table is well
# under a percent of a core.
AUTO_CAM_FAST_S = 2
AUTO_CAM_IDLE_S = 5
AUTO_CAM_OFF_S = 10


def auto_cam_on():
    return (appsettingGet('obs_auto_cam', '0') or '0') == '1'


def _probe_camera_dark(source):
    """True when the source's current frame is essentially black — a feed
    that stopped, a covered lens, or vdo.ninja's video-muted screen."""
    import base64
    import io

    import obs_ws
    from PIL import Image
    r = obs_ws.request('GetSourceScreenshot',
                       {'sourceName': source, 'imageFormat': 'png',
                        'imageWidth': 96, 'imageHeight': 54})
    raw = base64.b64decode(r['imageData'].split(',', 1)[1])
    img = Image.open(io.BytesIO(raw)).convert('L')
    hist = img.histogram()
    total = sum(hist) or 1
    mean = sum(i * n for i, n in enumerate(hist)) / total
    return mean < AUTO_CAM_LUMA


def _scan_cameras():
    """One detection pass over every configured camera. Never raises; a tile
    OBS can't screenshot right now (scene not built, source busy) simply
    casts no vote and keeps its current state."""
    import obs_ws
    if not (auto_cam_on() and obs_ws.connected()):
        if _auto_dark_ids or _cam_dark_votes:
            _auto_dark_ids.clear()
            _cam_dark_votes.clear()
        return
    for char in _ordered_party():
        if not char.video_view_url():
            continue
        cid = char.character_id
        try:
            dark = _probe_camera_dark(_source_name_for(char))
        except Exception:
            continue
        if dark:
            _cam_dark_votes[cid] = _cam_dark_votes.get(cid, 0) + 1
            if _cam_dark_votes[cid] >= AUTO_CAM_DARK_PASSES:
                _auto_dark_ids.add(cid)
        else:
            _cam_dark_votes[cid] = 0
            _auto_dark_ids.discard(cid)


def _cam_watch_seconds():
    """How long until the next camera pass, from what the last one saw."""
    import obs_ws
    if not (auto_cam_on() and obs_ws.connected()):
        return AUTO_CAM_OFF_S
    if _auto_dark_ids or any(_cam_dark_votes.values()):
        return AUTO_CAM_FAST_S
    return AUTO_CAM_IDLE_S


def start_cam_watch(app_obj, delay=None):
    """Idempotent self-pacing camera watch (see the AUTO_CAM_* notes). Call
    again with delay=0 to run a pass right away, e.g. when auto-cam is
    switched on or the party scene is rebuilt."""
    global _cam_timer

    def _tick():
        try:
            with app_obj.app_context():
                if appsettingGet('obs_enabled', '0') == '1':
                    before = set(_auto_dark_ids)
                    _scan_cameras()
                    if _auto_dark_ids != before:
                        refresh_tiles()   # swap now, not on the feed watch
                    nxt = _cam_watch_seconds()
                else:
                    nxt = AUTO_CAM_OFF_S
        except Exception as exc:          # a watchdog must never die loudly
            log.info('OBS camera watch failed: %s', exc)
            nxt = AUTO_CAM_IDLE_S
        finally:
            start_cam_watch(app_obj, nxt)

    with _watch_lock:
        if _cam_timer is not None:
            _cam_timer.cancel()
        if delay is None:
            with app_obj.app_context():
                delay = _cam_watch_seconds()
        _cam_timer = threading.Timer(delay, _tick)
        _cam_timer.daemon = True
        _cam_timer.start()


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
        want = _tile_plan(char, presence, overrides)
        if _tile_urls.get(char.character_id) == want:
            continue
        url, overlay = want
        try:
            # The camera source usually does NOT change here — it stays on the
            # feed so the player keeps their microphone. What swaps is the
            # overlay above it, between the name strip and the stat card.
            for source, u in ((_source_name_for(char), url),
                              (_overlay_source_name_for(char), overlay)):
                if u is None:
                    continue
                prev = _input_settings.get(source)
                if prev and prev[0] == u:
                    continue
                obs_ws.set_browser_url(source, u)
                # Keep the settings cache honest, or the next sync would decide
                # the URL still differs and rewrite it a second time.
                if prev:
                    _input_settings[source] = (u, prev[1], prev[2])
            _tile_urls[char.character_id] = want
            swapped.append(char.name)
        except (obs_ws.ObsRejected, obs_ws.ObsUnavailable) as exc:
            # The scene may not be built yet — not worth a stack trace.
            log.info('Tile refresh skipped for %s: %s', char.name, exc)
    if swapped:
        log.info('OBS tiles swapped for: %s', ', '.join(swapped))
    return swapped


def rebind_music_if_stale():
    """Re-point the music capture when the sink underneath it was replaced.

    The music player stamps obs_music_sink_epoch every time it builds a new
    capture sink. OBS, meanwhile, holds a handle to the sink instance that
    existed when its source was created — so a player restart leaves the
    source reading the correct device name, unmuted, and completely silent.
    That is the failure this table kept hitting: nothing looks wrong anywhere.

    Cheap: two settings reads and an early return on the normal pass, when the
    stamp has not moved. Returns True only when it actually re-bound."""
    import obs_ws
    epoch = (appsettingGet('obs_music_sink_epoch', '') or '').strip()
    if not epoch or epoch == (appsettingGet('obs_music_bound_epoch', '') or ''):
        return False
    # Only the device path binds to a sink at all; a vdo.ninja feed has no
    # local device to go stale, and 'off' has nothing to re-bind.
    if music_transport() != 'device' or not obs_ws.connected():
        return False
    party = party_scene_name()
    try:
        if MUSIC_SOURCE_NAME not in obs_ws.scene_items(party):
            return False        # not built yet — a build will bind it fresh
        obs_ws.ensure_audio_input(party, MUSIC_SOURCE_NAME, music_device_id())
    except (obs_ws.ObsRejected, obs_ws.ObsUnavailable) as exc:
        log.info('Music re-bind skipped: %s', exc)
        return False
    appsettingSet('obs_music_bound_epoch', epoch)
    log.info('Music capture re-bound: the sink was replaced underneath it')
    return True


# ── the dice reflow: slide the roll panel in, give the room back after ───────
DICE_REFLOW_HOLD_S = 5          # quiet seconds before the panel slides away
DICE_REFLOW_ANIM_S = 0.6
_dice_state = {'shown': False, 'last_id': None, 'last_roll_at': 0.0,
               'threads': [],
               # The DM's panel note is a pop trigger too: a fresh note slides
               # the panel in just like a roll, and whichever of the two
               # happened LAST is what the panel shows.
               'note_text': None, 'note_stamp': 0.0, 'roll_stamp': 0.0}
_dice_timer = None
_dice_lock = threading.Lock()


def _newest_roll_id():
    """max(roll_id), straight from sqlite — runs every second, must be cheap,
    and rolls arrive from another PROCESS too (the relay writes them
    directly), so an in-app hook could never see them all."""
    import sqlite3
    from extensions import databaseDir
    try:
        con = sqlite3.connect(databaseDir, timeout=1.0)
        row = con.execute('SELECT max(roll_id) FROM tblDiceRolls').fetchone()
        con.close()
        return row[0] if row else None
    except Exception:
        return None


def _dice_reflow(show):
    """Make room for the dice, or give it back — by MOVING things, not by
    covering them.

    In: every tile eases into the panel-on grid while the roll panel slides
    in from off-canvas. Out: the reverse, and the tiles retake the full
    width. The map scene gets the same treatment. All eased through
    animate_items, the same engine the spotlight uses, so nothing snaps."""
    import obs_ws
    if not obs_ws.connected():
        return False
    snap = obs_ws.current_state()
    w = snap.get('base_width') or 1920
    h = snap.get('base_height') or 1080
    withp = obs_layout.frame_areas(w, h, panel_side(), panel_fraction(),
                                   title_height(), True)
    full = obs_layout.frame_areas(w, h, panel_side(), panel_fraction(),
                                  title_height(), False)
    if withp['panel'] is None:
        return False
    px, py, pw, ph = withp['panel']
    panel_box = {'x': px, 'y': py, 'w': pw, 'h': ph}
    panel_off = dict(panel_box, x=float(w))

    try:
        gutter = int(appsettingGet('obs_tile_gutter', '')
                     or obs_layout.DEFAULT_GUTTER)
    except (TypeError, ValueError):
        gutter = obs_layout.DEFAULT_GUTTER

    party = party_scene_name()
    try:
        items = obs_ws.scene_items(party)
        members = _ordered_party()
        fid = featured_id()
        fidx = next((i for i, c in enumerate(members)
                     if c.character_id == fid), None)
        area = withp['tiles'] if show else full['tiles']
        rects = obs_layout.grid_layout(len(members), w, h, featured=fidx,
                                       gutter=gutter, area=area)
        moves = []
        for char, rect in zip(members, rects):
            target = {k: rect[k] for k in ('x', 'y', 'w', 'h')}
            was = _tile_rects.get(char.character_id) or target
            for name in (_source_name_for(char),
                         _overlay_source_name_for(char)):
                iid = items.get(name)
                if iid is not None:
                    moves.append((iid, was, target))
            _tile_rects[char.character_id] = target
        pid = items.get(PANEL_SOURCE_NAME)
        if pid is not None:
            moves.append((pid, panel_off if show else panel_box,
                          panel_box if show else panel_off))
        if moves:
            t = obs_ws.animate_items(party, moves,
                                     duration_s=DICE_REFLOW_ANIM_S)
            if t is not None:
                _dice_state['threads'].append(t)
    except (obs_ws.ObsRejected, obs_ws.ObsUnavailable) as exc:
        log.info('Dice reflow (party) skipped: %s', exc)
        return False

    # The map scene: the map itself breathes in and out the same way.
    try:
        mscene = map_scene_name()
        mitems = obs_ws.scene_items(mscene)
        moves = []
        m_show = {'x': withp['tiles'][0], 'y': withp['tiles'][1],
                  'w': withp['tiles'][2], 'h': withp['tiles'][3]}
        m_full = {'x': full['tiles'][0], 'y': full['tiles'][1],
                  'w': full['tiles'][2], 'h': full['tiles'][3]}
        mid = mitems.get(MAP_SOURCE_NAME)
        if mid is not None:
            moves.append((mid, m_full if show else m_show,
                          m_show if show else m_full))
        did = mitems.get(DICE_SOURCE_NAME)
        if did is not None:
            moves.append((did, panel_off if show else panel_box,
                          panel_box if show else panel_off))
        if moves:
            t = obs_ws.animate_items(mscene, moves,
                                     duration_s=DICE_REFLOW_ANIM_S)
            if t is not None:
                _dice_state['threads'].append(t)
    except (obs_ws.ObsRejected, obs_ws.ObsUnavailable) as exc:
        log.info('Dice reflow (map) skipped: %s', exc)
    return True


def _dice_tick(now):
    """One heartbeat of the roll watcher. Factored for tests: hand it a
    clock, it decides show/hide."""
    st = _dice_state
    # Never start a reflow while the previous one is still ANIMATING: two
    # animation threads writing the same transforms interleave, and whichever
    # finishes LAST wins — measured, with the panel ending up in whichever
    # state was supposed to be gone. The guard watches the actual threads,
    # not a clock: against a remote OBS every frame is a round-trip, so the
    # 0.6s animation can take several real seconds. A roll arriving mid-slide
    # is not lost; the next tick acts on it.
    st['threads'] = [t for t in st['threads'] if t.is_alive()]
    if st['threads']:
        return
    newest = _newest_roll_id()
    note = '\n'.join(_info_lines())
    if st['last_id'] is None:
        # First look: whatever is already in the feed is history, not an
        # event — coming up mid-session must not slide the panel in. The
        # note text already on record is history for the same reason.
        st['last_id'] = newest
        st['note_text'] = note
        return
    changed = False
    if newest != st['last_id']:
        st['last_id'] = newest
        st['roll_stamp'] = now
        changed = True
    if note != st['note_text']:
        st['note_text'] = note
        # An emptied note is not an announcement — it just stops showing.
        if note.strip():
            st['note_stamp'] = now
            changed = True
    # A roll or a fresh note is an EVENT: it slides the panel in and restarts
    # the hold. Text still sitting in the box is STATE: it keeps the panel on
    # screen indefinitely — the hold only sends the panel away once the box
    # is empty.
    standing = bool(note.strip())
    if changed:
        st['last_roll_at'] = now
    if changed or standing:
        if not st['shown'] and _dice_reflow(True):
            st['shown'] = True
    if (st['shown'] and not changed
            and now - st['last_roll_at'] > DICE_REFLOW_HOLD_S):
        if standing:
            # The roll's moment has passed: the standing note takes the
            # panel back rather than the panel sliding away.
            if st['note_stamp'] < st['roll_stamp']:
                st['note_stamp'] = now
        elif _dice_reflow(False):
            st['shown'] = False


def start_dice_watch(app_obj):
    """1s heartbeat while OBS control is on. Cheap: one MAX() on sqlite and
    an early return unless something changed. It has to be a poll — rolls
    also arrive from the relay portal, which writes the table from a
    different process where no in-app hook could see them."""
    global _dice_timer

    def _tick():
        try:
            with app_obj.app_context():
                if (appsettingGet('obs_enabled', '0') == '1'
                        and panel_on() and dice_autohide_on()):
                    with _dice_lock:
                        _dice_tick(time.time())
        except Exception as exc:          # a watchdog must never die loudly
            log.info('Dice watch failed: %s', exc)
        finally:
            start_dice_watch(app_obj)

    with _watch_lock:
        if _dice_timer is not None:
            _dice_timer.cancel()
        _dice_timer = threading.Timer(1.0, _tick)
        _dice_timer.daemon = True
        _dice_timer.start()


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
                    refresh_tiles()      # presence / pin changes; the pixel
                                         # watch has its own faster timer
                    rebind_music_if_stale()
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
    # The camera watch starts (or restarts) with the feed watch at every
    # call site: boot, enabling OBS, and a party rebuild.
    start_cam_watch(app_obj, 0)


def stop_feed_watch():
    global _watch_timer, _dice_timer, _cam_timer
    with _watch_lock:
        if _watch_timer is not None:
            _watch_timer.cancel()
            _watch_timer = None
        if _cam_timer is not None:
            _cam_timer.cancel()
            _cam_timer = None
        if _dice_timer is not None:
            _dice_timer.cancel()
            _dice_timer = None


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
    # "Everyone on screen" means letting go of BOTH holds on one character:
    # the enlarged tile and the map pinned to their eyes. Releasing only the
    # tile left the battle map still staring through whoever it was.
    _set_viewed_character(None)
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

def _scanned_obs_servers():
    """Boxes the Servers-page LAN scan saw with obs-websocket open — any
    tblServersIP row whose ports column lists 4455. Offered as a pick-list so
    the DM selects the rig by name instead of remembering its IP. The ports
    column is the signal (not the OBS role): a box running ScenePlay AND OBS
    keeps its ScenePlay role but still belongs in this list."""
    from discovery import OBS_PORT
    from models.serverIP import tblserversip as ServerIP
    out = []
    for row in ServerIP.query.all():
        ports = {p.strip() for p in (row.ports or '').split(',')}
        if str(OBS_PORT) in ports and (row.ipAddress or '').strip():
            out.append({'ip': row.ipAddress.strip(),
                        'name': (row.serverName or '').strip()
                        or row.ipAddress.strip()})
    return sorted(out, key=lambda d: d['name'].lower())


@obs_bp.route('/')
@login_required
@dm_required
def broadcast():
    import obs_ws
    # First visit auto-configures where OBS fetches stat cards from: whatever
    # address the DM is reaching ScenePlay on is one OBS can reach too, in the
    # normal same-machine / same-LAN setup.
    if not (appsettingGet('obs_card_base', '') or '').strip():
        appsettingSet('obs_card_base', suggested_card_base())
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
                               'obs_scene': linked.get(sc.scene_ID, ''),
                               'audio': scene_audio_policy(sc.scene_ID)})
    return render_template('ttrpg/obs_broadcast.html',
                           cfg=cfg, snap=snap,
                           rows=_mapping_rows(party, snap),
                           scene_rows=scene_rows,
                           problems=_problems(cfg, snap),
                           dm_enabled=dm_tile_enabled(),
                           dm_id=DM_TILE_ID,
                           map_token=_map_token(),
                           has_party=bool(party),
                           obs_servers=_scanned_obs_servers())


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


def scene_link_map():
    """{ScenePlay scene_id: OBS scene name} for every scene that drives OBS.

    Bulk, because the callers render a whole sidebar of scene buttons and a
    query per button would be paid on every battle-map load."""
    try:
        return {r.entity_id: r.scene_name for r in
                tblObsSceneMap.query.filter_by(entity_type='scene').all()
                if r.scene_name}
    except Exception:
        return {}


def scene_links_live():
    """Will activating a mapped scene ACTUALLY move OBS right now?

    A mapping alone is not enough — obs_scene_link gates the whole feature,
    and a scene mapped while that is off looks identical to one that works.
    Distinguishing the two is the entire point of showing a marker."""
    return ((appsettingGet('obs_enabled', '0') or '0') == '1'
            and (appsettingGet('obs_scene_link', '0') or '0') == '1')


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
        start_dice_watch(current_app._get_current_object())
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
    base = (request.form.get('obs_card_base', '') or '').strip().rstrip('/')
    if base:
        appsettingSet('obs_card_base', base)
    appsettingSet('obs_feed_noaudio',
                  '1' if request.form.get('obs_feed_noaudio') else '0')
    appsettingSet('obs_dm_audio',
                  '1' if request.form.get('obs_dm_audio') else '0')
    appsettingSet('obs_feed_monitor',
                  '1' if request.form.get('obs_feed_monitor') else '0')
    if 'obs_music_transport' in request.form:
        mode = (request.form.get('obs_music_transport', '') or 'auto').strip()
        if mode not in MUSIC_TRANSPORTS:
            mode = 'auto'
        appsettingSet('obs_music_transport', mode)
        # Kept in step with the select, which is now the ONLY control. It used
        # to be a checkbox of its own meaning the same thing as "off", so the
        # two could be set against each other with nothing on the page to show
        # it — and whichever said "no" won, invisibly.
        appsettingSet('obs_music_capture', '0' if mode == 'off' else '1')
    if 'obs_dm_mic_label' in request.form:
        appsettingSet('obs_dm_mic_label',
                      (request.form.get('obs_dm_mic_label', '')
                       or '').strip()[:120])
    # Only when it was actually sent: the field is DISABLED while the local
    # device path is in use, and a disabled field submits nothing. Writing a
    # blank then would quietly discard the DM's vdo.ninja device name every
    # time they saved from the other path.
    label = (request.form.get('obs_music_device_label') or '').strip()
    if label:
        appsettingSet('obs_music_device_label', label[:120])
    # Same disabled-field rule, but an empty value here is a real choice
    # ("just use the default output"), so presence — not truthiness — decides.
    if 'music_output_device' in request.form:
        appsettingSet('music_output_device',
                      (request.form.get('music_output_device', '')
                       or '').strip()[:200])
    # Checkbox is "players SEE each other" — the inverse of the stored flag,
    # so an unticked (absent) box lands on the safe audio-only default.
    appsettingSet('obs_room_audio_only',
                  '0' if request.form.get('obs_room_video') else '1')
    if 'obs_room_videobitrate' in request.form:
        from models.ttrpg import (ROOM_BITRATE_DEFAULT, ROOM_BITRATE_MIN,
                                  ROOM_BITRATE_MAX)
        try:
            v = int(float(request.form.get('obs_room_videobitrate', '')
                          or ROOM_BITRATE_DEFAULT))
        except (TypeError, ValueError):
            v = ROOM_BITRATE_DEFAULT
        appsettingSet('obs_room_videobitrate',
                      str(max(ROOM_BITRATE_MIN, min(v, ROOM_BITRATE_MAX))))
    if 'obs_vdo_room' in request.form:
        # Strip a pasted full URL down to the room name: the DM is far more
        # likely to have a vdo.ninja link to hand than the bare word.
        room = (request.form.get('obs_vdo_room', '') or '').strip()
        if 'room=' in room:
            room = room.split('room=', 1)[1].split('&')[0]
        room = unquote(room)
        safe = clean_room(room)
        # Say so rather than silently storing something different: a room name
        # that quietly lost its punctuation would put the DM in one room and
        # everyone still holding the old link in another.
        if room and safe != room:
            flash(f'Room name adjusted to "{safe}" — vdo.ninja rooms must be '
                  f'alphanumeric and at most {ROOM_MAX} characters.')
        if safe != table_room():
            appsettingSet('obs_vdo_room', safe)
            repush_feeds('room changed')
        else:
            appsettingSet('obs_vdo_room', safe)
    appsettingSet('obs_panel_on',
                  '1' if request.form.get('obs_panel_on') else '0')
    appsettingSet('obs_dice_autohide',
                  '1' if request.form.get('obs_dice_autohide') else '0')
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
    # Stream look. Only well-formed values land; anything else keeps the
    # current setting rather than wedging the pages on a broken colour.
    # Same ownership rule as the show art: with a session running the look is
    # THAT session's; with none it edits the shared default they inherit.
    _sid = _active_session_id()
    _sfx = f':s{_sid}' if _sid is not None else ''
    for key in ('obs_accent_color', 'obs_base_color', 'obs_base_color2',
                'obs_plate_color', 'obs_plate_color2'):
        colour = (request.form.get(key, '') or '').strip()
        if re.fullmatch(r'#[0-9a-fA-F]{6}', colour):
            appsettingSet(f'{key}{_sfx}', colour)
    for key in ('obs_base_dir', 'obs_plate_dir'):
        direction = (request.form.get(key, '') or '').strip().lower()
        if direction in BASE_DIRS:
            appsettingSet(f'{key}{_sfx}', direction)
    shape = (request.form.get('obs_bezel_shape', '') or '').strip().lower()
    if shape in BEZEL_SHAPES:
        appsettingSet(f'obs_bezel_shape{_sfx}', shape)
    design = (request.form.get('obs_card_design', '') or '').strip().lower()
    if design in CARD_DESIGNS:
        appsettingSet(f'obs_card_design{_sfx}', design)
    tdesign = (request.form.get('obs_tile_design', '') or '').strip().lower()
    if tdesign in TILE_DESIGNS:
        appsettingSet(f'obs_tile_design{_sfx}', tdesign)
    icon = (request.form.get('obs_dm_icon', '') or '').strip()
    if icon in DM_ICONS:
        appsettingSet(f'obs_dm_icon{_sfx}', icon)
    if 'obs_dm_title' in request.form:
        appsettingSet(f'obs_dm_title{_sfx}',
                      (request.form.get('obs_dm_title', '') or '').strip()[:40])
    # Kept verbatim, newlines and all: each line is one row in the panel.
    appsettingSet('obs_info_text',
                  (request.form.get('obs_info_text', '') or '')[:4000])
    # YouTube go-live front matter. Guarded on the client-id field so a
    # partial post (tests, older pages) cannot blank the lot; the secret
    # keeps the blank-means-keep rule the other passwords use.
    if 'yt_client_id' in request.form:
        import youtube_live as yt
        appsettingSet('yt_client_id',
                      (request.form.get('yt_client_id', '') or '').strip()[:200])
        secret = (request.form.get('yt_client_secret', '') or '').strip()
        if secret:
            appsettingSet('yt_client_secret', secret[:200])
        appsettingSet('yt_title',
                      (request.form.get('yt_title', '') or '').strip()[:100])
        appsettingSet('yt_description',
                      (request.form.get('yt_description', '') or '')[:5000])
        privacy = (request.form.get('yt_privacy', '') or '').strip().lower()
        if privacy in yt.PRIVACIES:
            appsettingSet('yt_privacy', privacy)
        category = (request.form.get('yt_category', '') or '').strip()
        if category in dict(yt.CATEGORIES):
            appsettingSet('yt_category', category)
        appsettingSet('yt_kids',
                      '1' if request.form.get('yt_kids') else '0')
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
    # The page auto-saves on change: answer fetch with JSON so nothing
    # navigates. The redirect stays for plain form posts (no-JS fallback).
    if request.headers.get('X-Requested-With') == 'fetch':
        # The stored room may differ from what was typed (clean_room strips
        # punctuation and trims) — hand it back so the page can show what was
        # actually kept, since there is no reload to reveal it.
        return jsonify({'ok': True, 'reconnecting': bool(changed),
                        'room': table_room()})
    flash('OBS settings saved.' + (' Reconnecting.' if changed else ''))
    return redirect(url_for('obs_bp.broadcast'))


# ── JSON API ──────────────────────────────────────────────────────────────────

# ── going live on YouTube ─────────────────────────────────────────────────────
# The stream's front matter — title, description, privacy, category,
# made-for-kids, thumbnail — set HERE instead of in OBS's "Manage Broadcast"
# dialog on the streaming machine. youtube_live.py does the API work; these
# routes wire it to the page and to OBS.

def _yt_cfg():
    import youtube_live as yt
    return {
        'linked':      yt.linked(),
        'channel':     yt.channel_name(),
        'client_id':   (appsettingGet('yt_client_id', '') or '').strip(),
        'has_secret':  bool((appsettingGet('yt_client_secret', '') or '').strip()),
        'title':       (appsettingGet('yt_title', '') or '').strip(),
        'description': appsettingGet('yt_description', '') or '',
        'privacy':     (appsettingGet('yt_privacy', '') or '').strip()
                       or 'unlisted',
        'category':    (appsettingGet('yt_category', '') or '').strip() or '20',
        'kids':        (appsettingGet('yt_kids', '0') or '0') == '1',
        'categories':  yt.CATEGORIES,
        'privacies':   yt.PRIVACIES,
    }


@obs_bp.route('/api/yt/link', methods=['POST'])
@login_required
@dm_required
def api_yt_link():
    import youtube_live as yt
    try:
        return jsonify({'ok': True, **yt.link_start()})
    except yt.YtError as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 400
    except Exception as exc:                     # noqa: BLE001 - network
        log.info('YT link start failed: %s', exc)
        return jsonify({'ok': False,
                        'error': 'Could not reach Google to start '
                                 'linking — is this machine online?'}), 502


@obs_bp.route('/api/yt/link/poll', methods=['POST'])
@login_required
@dm_required
def api_yt_link_poll():
    import youtube_live as yt
    try:
        return jsonify({'ok': True, **yt.link_poll()})
    except yt.YtError as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 400
    except Exception as exc:                     # noqa: BLE001 - network
        log.info('YT link poll failed: %s', exc)
        return jsonify({'ok': True, 'state': 'pending'})


@obs_bp.route('/api/yt/unlink', methods=['POST'])
@login_required
@dm_required
def api_yt_unlink():
    import youtube_live as yt
    yt.unlink()
    return jsonify({'ok': True})


def _yt_thumb():
    """The uploaded thumbnail as (bytes, mime), or None. Silently skipped
    when it is missing, a video, or over YouTube's 2 MB cap — a bad
    thumbnail must never stop the stream."""
    name = art_setting('obs_yt_thumb')
    ext = name.rsplit('.', 1)[-1].lower() if '.' in name else ''
    if ext not in ('jpg', 'jpeg', 'png'):
        return None
    try:
        with open(os.path.join(BG_DIR, name), 'rb') as f:
            data = f.read()
    except OSError:
        return None
    if len(data) > 2 * 1024 * 1024:
        return None
    return (data, 'image/png' if ext == 'png' else 'image/jpeg')


@obs_bp.route('/api/yt/golive', methods=['POST'])
@login_required
@dm_required
def api_yt_golive():
    """One click: create the broadcast with tonight's front matter, point
    OBS's stream output at its ingestion, start streaming. enableAutoStart
    flips the broadcast live once frames arrive; the existing Stop-streaming
    button ends it (enableAutoStop)."""
    import obs_ws
    import youtube_live as yt
    if not obs_ws.connected():
        return jsonify({'ok': False, 'error': 'OBS is not connected.'}), 503
    title = (appsettingGet('yt_title', '') or '').strip()
    if not title:
        # Same derivation the title strip uses, so an unset title still
        # names the video after tonight's campaign or session.
        sess = tblSessions.query.filter_by(status='active').first()
        tp = _title_payload(sess)
        title = tp['campaign'] or tp['session'] or 'ScenePlay stream'
    try:
        res = yt.go_live(
            title,
            appsettingGet('yt_description', '') or '',
            (appsettingGet('yt_privacy', '') or '').strip() or 'unlisted',
            (appsettingGet('yt_category', '') or '').strip() or '20',
            (appsettingGet('yt_kids', '0') or '0') == '1',
            thumb=_yt_thumb(),
            start_iso=datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'))
    except yt.YtError as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 502
    except Exception as exc:                     # noqa: BLE001 - network
        log.info('YT go-live failed: %s', exc)
        return jsonify({'ok': False,
                        'error': 'Could not reach YouTube — is this '
                                 'machine online?'}), 502
    try:
        obs_ws.request('SetStreamServiceSettings', {
            'streamServiceType': 'rtmp_custom',
            'streamServiceSettings': {'server': res['server'],
                                      'key': res['key'], 'use_auth': False}})
        obs_ws.set_output_active('stream', True)
    except (obs_ws.ObsRejected, obs_ws.ObsUnavailable) as exc:
        return jsonify({'ok': False, 'watch_url': res['watch_url'],
                        'error': f'The broadcast is ready '
                                 f'({res["watch_url"]}) but OBS refused to '
                                 f'start streaming: {exc}'}), 502
    with obs_ws._cache_lock:
        obs_ws._cache['streaming'] = True
    return jsonify({'ok': True, 'watch_url': res['watch_url'],
                    'thumb_warning': res.get('thumb_warning', '')})


# ── saved panel notes ─────────────────────────────────────────────────────────
# A library of pre-written messages for the information panel. The DM preps
# them before the stream and pops one on with a click instead of typing live.
# A note belongs to ONE session's prep, or — session_id NULL — to every
# session. The library shows the ACTIVE session's notes plus the shared ones,
# the same scoping the show art and theme use.

def panel_note_rows():
    from sqlalchemy import or_
    from models.ttrpg import tblObsPanelNotes
    sid = _active_session_id()
    q = tblObsPanelNotes.query
    if sid is not None:
        q = q.filter(or_(tblObsPanelNotes.session_id.is_(None),
                         tblObsPanelNotes.session_id == sid))
    else:
        q = q.filter(tblObsPanelNotes.session_id.is_(None))
    rows = q.all()
    # The session's own notes first — they are tonight's — then the shared
    # stock, each block alphabetical.
    rows.sort(key=lambda r: (r.session_id is None, (r.title or '').lower()))
    return [{'id': r.note_id, 'title': r.title or '(untitled)',
             'shared': r.session_id is None} for r in rows]


@obs_bp.route('/api/panel-notes', methods=['POST'])
@login_required
@dm_required
def api_panel_note_save():
    """Create or update one saved note. Every reply carries the refreshed
    library so the page never has to guess what the list looks like now."""
    from models.ttrpg import tblObsPanelNotes
    from routes._util import _now
    data = request.get_json(silent=True) or {}
    title = (data.get('title') or '').strip()[:80]
    body = (data.get('body') or '')[:4000]
    if not title:
        return jsonify({'ok': False, 'error': 'A note needs a name.'}), 400
    if not body.strip():
        return jsonify({'ok': False,
                        'error': 'The note is empty — type the message '
                                 'into the box first.'}), 400
    sid = None if data.get('shared') else _active_session_id()
    row = None
    if data.get('note_id'):
        try:
            row = db.session.get(tblObsPanelNotes, int(data['note_id']))
        except (TypeError, ValueError):
            return jsonify({'ok': False, 'error': 'bad note_id'}), 400
    if row is None:
        row = tblObsPanelNotes(session_id=sid, title=title, body=body,
                               created_at=_now(), updated_at=_now())
        db.session.add(row)
    else:
        row.title, row.body, row.session_id = title, body, sid
        row.updated_at = _now()
    db.session.commit()
    return jsonify({'ok': True, 'note_id': row.note_id,
                    'notes': panel_note_rows()})


@obs_bp.route('/api/panel-notes/show', methods=['POST'])
@login_required
@dm_required
def api_panel_note_show():
    """Put one saved note on stream: it becomes the panel text, and the dice
    watcher pops the panel exactly as if the DM had typed it live."""
    from models.ttrpg import tblObsPanelNotes
    data = request.get_json(silent=True) or {}
    try:
        row = db.session.get(tblObsPanelNotes, int(data.get('note_id') or 0))
    except (TypeError, ValueError):
        row = None
    if row is None:
        return jsonify({'ok': False, 'error': 'No such saved note.'}), 404
    appsettingSet('obs_info_text', (row.body or '')[:4000])
    return jsonify({'ok': True, 'body': row.body or '',
                    'notes': panel_note_rows()})


@obs_bp.route('/api/panel-notes/delete', methods=['POST'])
@login_required
@dm_required
def api_panel_note_delete():
    from models.ttrpg import tblObsPanelNotes
    data = request.get_json(silent=True) or {}
    try:
        row = db.session.get(tblObsPanelNotes, int(data.get('note_id') or 0))
    except (TypeError, ValueError):
        row = None
    if row is None:
        return jsonify({'ok': False, 'error': 'No such saved note.'}), 404
    db.session.delete(row)
    db.session.commit()
    return jsonify({'ok': True, 'notes': panel_note_rows()})


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


@obs_bp.route('/api/look-at', methods=['POST'])
@login_required
@dm_required
def api_look_at():
    """Point the 3D view at a spot on the map.

    Cheap and stateless: the cell is stashed in settings and the map source
    picks it up on its next poll. Deliberately NOT gated on OBS being
    connected — this steers the browser source, which renders whether or not
    the rig is up."""
    data = request.get_json(silent=True) or {}
    try:
        col, row = int(data.get('col')), int(data.get('row'))
    except (TypeError, ValueError):
        return jsonify({'ok': False, 'error': 'col and row required'}), 400
    if viewed_character_id() is None:
        # Nothing is being viewed through, so there is no eye to turn.
        return jsonify({'ok': False, 'error': 'No character is being viewed.',
                        'no_pin': True}), 409
    # Monotonic-enough sequence: two clicks on the SAME cell must both count.
    seq = int(time.time() * 1000) % 2_000_000_000
    appsettingSet('obs_look_at', f'{col},{row},{seq}')
    return jsonify({'ok': True, 'col': col, 'row': row, 'seq': seq})


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
    # Arm the same clock the spotlight uses. Pinning the map to one character
    # is the other way a session gets stranded on one person, and it used to
    # be the way with NO way back — the auto-return never armed here, so the
    # pin held until the DM went and released it by hand.
    _after_switch('')
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


@obs_bp.route('/api/mute', methods=['POST'])
@login_required
@dm_required
def api_mute():
    """Mute or unmute voices on the stream: one character, or every player.

    {'character_id': id, 'muted': bool}  — one person (the DM included)
    {'all': True, 'muted': bool}         — every player; the DM is deliberately
                                           left out, since "mute the table" and
                                           "mute myself" are different acts.

    Persisted first, then pushed to OBS: builds re-assert tile audio, so a
    mute that lived only in OBS would silently lift on the next rebuild."""
    data = request.get_json(silent=True) or {}
    muted = bool(data.get('muted'))

    scope = data.get('all')
    if scope:
        # True (legacy) and 'players' spare the DM; 'everyone' includes them —
        # the whole-table silence for free talk before the show.
        targets = [c for c in _ordered_party()
                   if scope == 'everyone' or c.character_id != DM_TILE_ID]
    else:
        try:
            cid = int(data.get('character_id'))
        except (TypeError, ValueError):
            return jsonify({'ok': False, 'error': 'character_id required'}), 400
        char = (dm_tile() if cid == DM_TILE_ID
                else db.session.get(tblCharacters, cid))
        if char is None:
            return jsonify({'ok': False, 'error': 'No such character.'}), 404
        targets = [char]

    failed = _apply_mutes(targets, muted)
    return jsonify({'ok': True, 'muted': muted,
                    'muted_ids': sorted(_muted_ids()),
                    'applied_later': failed})


def _apply_mutes(targets, muted):
    """Persist then push each mute; returns names OBS couldn't take yet."""
    import obs_ws
    failed = []
    for char in targets:
        _set_muted(char.character_id, muted)
        if not obs_ws.connected():
            continue        # the setting holds; the next build applies it
        try:
            obs_ws.set_input_mute(_source_name_for(char), muted)
        except (obs_ws.ObsRejected, obs_ws.ObsUnavailable):
            # Not built yet, or the source is a stat card — the persisted
            # setting still wins on the next build.
            failed.append(char.name)
    return failed


SCENE_AUDIO_POLICIES = ('', 'mute_players', 'mute_all', 'unmute_all')


def scene_audio_policy(scene_id):
    """What activating this ScenePlay scene does to the stream's voices."""
    v = (appsettingGet(f'obs_scene_audio:{int(scene_id)}', '') or '').strip()
    return v if v in SCENE_AUDIO_POLICIES else ''


def apply_scene_audio(scene_id):
    """Apply a scene's stream-audio policy — called when the scene activates.

    This is what lets a PreShow scene carry 'mute everyone' with it: the table
    talks freely in the room while the broadcast shows the pre-show card in
    silence, and the opening scene flips everyone audible again. Same
    persistence as the buttons, so a rebuild mid-scene keeps the policy.

    Returns the policy applied ('' when none). Never raises: activating a
    scene must survive OBS being off, gone, or wrong."""
    try:
        if (appsettingGet('obs_enabled', '0') or '0') != '1':
            return ''
        policy = scene_audio_policy(scene_id)
        if not policy:
            return ''
        everyone = _ordered_party()
        if policy == 'mute_players':
            _apply_mutes([c for c in everyone
                          if c.character_id != DM_TILE_ID], True)
        elif policy == 'mute_all':
            _apply_mutes(everyone, True)
        elif policy == 'unmute_all':
            _apply_mutes(everyone, False)
        return policy
    except Exception as exc:                   # noqa: BLE001
        log.info('Scene audio policy skipped for %s: %s', scene_id, exc)
        return ''


@obs_bp.route('/api/scene-audio', methods=['POST'])
@login_required
@dm_required
def api_scene_audio():
    """Store one ScenePlay scene's stream-audio policy."""
    data = request.get_json(silent=True) or {}
    try:
        scene_id = int(data.get('scene_id'))
    except (TypeError, ValueError):
        return jsonify({'ok': False, 'error': 'scene_id required'}), 400
    policy = (data.get('policy') or '').strip()
    if policy not in SCENE_AUDIO_POLICIES:
        return jsonify({'ok': False, 'error': f'Unknown policy {policy!r}'}), 400
    appsettingSet(f'obs_scene_audio:{scene_id}', policy)
    return jsonify({'ok': True, 'scene_id': scene_id, 'policy': policy})


@obs_bp.route('/api/output/<kind>', methods=['POST'])
@login_required
@dm_required
def api_output(kind):
    """Start or stop OBS's recording / streaming.

    Deliberately explicit rather than a toggle: a toggle acts on what the page
    last heard, so a double-click, a stale poll, or the DM having hit the key
    inside OBS turns "stop" into "start" and puts the broadcast live again."""
    import obs_ws
    if kind not in obs_ws.OUTPUTS:
        return jsonify({'ok': False, 'error': f'Unknown output {kind!r}'}), 400
    if not obs_ws.connected():
        return jsonify({'ok': False, 'error': 'OBS is not connected.'}), 503
    want = bool((request.get_json(silent=True) or {}).get('on'))
    # Deliberately NO room rotation here. A per-stream room sounded like
    # security but was a trap: the new room is empty while every player's open
    # camera tab is still in the old one, so OBS re-points to it and the whole
    # table goes black and silent right as the show starts — and no code can
    # move a player's browser tab for them. The GUID room is unguessable; the
    # New-room button covers an actually leaked link, at a moment the DM
    # chooses.
    try:
        now = obs_ws.set_output_active(kind, want)
    except obs_ws.ObsRejected as exc:
        obs_ws._record_error(f'{kind}-{"start" if want else "stop"}', exc)
        return jsonify({'ok': False,
                        'error': f'OBS refused: {exc.comment or exc}'}), 502
    except obs_ws.ObsUnavailable as exc:
        obs_ws._record_error(f'{kind}-{"start" if want else "stop"}', exc)
        return jsonify({'ok': False, 'error': 'Lost the OBS connection.'}), 503
    # Keep the cached snapshot honest so the next poll cannot flicker the
    # button back to its old label before the event lands.
    with obs_ws._cache_lock:
        obs_ws._cache['recording' if kind == 'record' else 'streaming'] = now
    return jsonify({'ok': True, 'kind': kind, 'active': now,
                    **{('recording' if kind == 'record' else 'streaming'): now}})


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
    for anyone at the table this is what the DM reaches for.

    {'character_id': id, 'show_card': bool} — one player
    {'all': True, 'show_card': bool}        — everyone with a tile, the DM
                                              included (the strip's CARD ON /
                                              CARD OFF buttons: "cards up"
                                              for a break, cameras back after)."""
    data = request.get_json(silent=True) or {}
    on = bool(data.get('show_card'))
    if data.get('all'):
        for char in _ordered_party():
            _set_card_override(char.character_id, on)
        swapped = refresh_tiles()
        return jsonify({'ok': True, 'all': True, 'show_card': on,
                        'card_ids': sorted(_card_overrides()),
                        'swapped': swapped})
    try:
        character_id = int(data.get('character_id') or 0)
    except (TypeError, ValueError):
        return jsonify({'ok': False, 'error': 'bad character_id'}), 400
    if not character_id:
        return jsonify({'ok': False, 'error': 'character_id required'}), 400
    _set_card_override(character_id, on)
    swapped = refresh_tiles()
    return jsonify({'ok': True, 'character_id': character_id,
                    'show_card': on, 'card_ids': sorted(_card_overrides()),
                    'swapped': swapped})


@obs_bp.route('/api/auto-cam', methods=['POST'])
@login_required
@dm_required
def api_auto_cam():
    """Toggle the auto-camera watch: dark feeds swap to the stat card, light
    coming back swaps to the camera. Runs one pass immediately so the button
    acts now rather than on the next watch tick."""
    data = request.get_json(silent=True) or {}
    on = bool(data.get('on'))
    appsettingSet('obs_auto_cam', '1' if on else '0')
    swapped = []
    try:
        _scan_cameras()             # also clears the state when turning OFF
        swapped = refresh_tiles()
    except Exception as exc:
        log.info('auto-cam first pass skipped: %s', exc)
    # Re-pace the watch now rather than waiting out the OFF interval.
    start_cam_watch(current_app._get_current_object())
    return jsonify({'ok': True, 'on': on, 'swapped': swapped})


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


@obs_bp.route('/api/reload-sources', methods=['POST'])
@login_required
@dm_required
def api_reload_sources():
    """Force every ScenePlay browser source to re-fetch its page.

    A browser source caches whatever it first loaded, so a source created
    while the page address was wrong keeps showing that blank result forever —
    correct box, correct URL in its settings, nothing on screen. Rebuilding
    does not fix it; only a refresh does."""
    import obs_ws
    if not obs_ws.connected():
        return jsonify({'ok': False, 'error': 'OBS is not connected.'}), 503
    wanted = {BG_SOURCE_NAME, TITLE_SOURCE_NAME, PANEL_SOURCE_NAME,
              DICE_SOURCE_NAME, MAP_SOURCE_NAME, *SHOW_SOURCE.values()}
    # ...plus every player/DM tile, whose names carry the managed prefixes.
    scenes = [party_scene_name(), map_scene_name(), pre_scene_name(),
              intermission_scene_name(), post_scene_name()]
    for sc in scenes:
        try:
            for src in obs_ws.scene_items(sc):
                if src.startswith(_MANAGED_PREFIXES):
                    wanted.add(src)
        except (obs_ws.ObsRejected, obs_ws.ObsUnavailable):
            pass
    done, failed = [], []
    for src in sorted(wanted):
        try:
            obs_ws.refresh_browser_source(src)
            done.append(src)
        except (obs_ws.ObsRejected, obs_ws.ObsUnavailable) as exc:
            # 600 = the source isn't in this collection; that is not an error
            # worth showing, it just means the DM has not built that scene.
            if getattr(exc, 'code', None) != 600:
                failed.append(f'{src} ({exc})')
    return jsonify({'ok': True, 'refreshed': done, 'failed': failed})


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
    'yt_thumb':     ('obs_yt_thumb', 'yt-thumb',
                     'YouTube thumbnail — 1280×720 JPG/PNG, under 2 MB'),
}

# Show art can also be a looping VIDEO — an animated title card or an ambient
# background. Videos skip the Pillow downscale (it cannot read them) and are
# rendered by the pages as <video autoplay muted loop>.
VIDEO_EXT = {'mp4', 'webm'}
VIDEO_MAX_BYTES = 200 * 1024 * 1024


def _active_session_id():
    sess = tblSessions.query.filter_by(status='active').first()
    return sess.session_id if sess else None


def art_setting(setting):
    """The art for one slot: this session's own choice first, else the shared
    default.

    Per-session values live in the same settings table under a derived key
    ('obs_post_image:s7') — the established no-migration idiom here — so each
    session can carry its own pre/post/title/background art while a session
    that never set any simply inherits the shared set."""
    sid = _active_session_id()
    if sid is not None:
        own = (appsettingGet(f'{setting}:s{sid}', '') or '').strip()
        if own:
            return own
    return (appsettingGet(setting, '') or '').strip()


def image_slots():
    """Slot rows for the Broadcast page: what is set, where it lives, and
    whether it is this session's own art or the shared default."""
    sid = _active_session_id()
    out = []
    for slot, (setting, _stem, label) in IMAGE_SLOTS.items():
        own = ((appsettingGet(f'{setting}:s{sid}', '') or '').strip()
               if sid is not None else '')
        name = own or (appsettingGet(setting, '') or '').strip()
        out.append({
            'slot': slot, 'label': label, 'file': name,
            'per_session': bool(own),
            'is_video': name.rsplit('.', 1)[-1].lower() in VIDEO_EXT
                        if '.' in name else False,
            'url': (url_for('static', filename=f'uploads/obs/{name}',
                            v=_art_mtime(name))
                    if name else ''),
        })
    return out


def _art_mtime(name):
    try:
        return int(os.path.getmtime(os.path.join(BG_DIR, name)))
    except OSError:
        return 0


def _art_url(name):
    """Absolute URL for an uploaded art file, VERSIONED by the file's mtime.

    Art filenames are stable per slot (a re-upload overwrites the same name),
    which keeps old files from piling up — but a browser source caches by
    URL, so without the version stamp a re-upload changed nothing on stream
    until the source was reloaded by hand. The stamp makes every re-upload a
    new URL: the pages' paint guards see a change and the fetch skips the
    cache, so new art lands within one poll."""
    if not name:
        return ''
    return f'{_card_base()}/static/uploads/obs/{name}?v={_art_mtime(name)}'


def show_cfg(kind):
    """Image, title and title placement for the pre- or post-show card.

    'pre' deliberately shares obs_title_image with the map's idle card: it is
    the same "we're about to start" art, and keeping one setting means the DM
    uploads it once instead of keeping two copies in step."""
    slot = {'pre': 'title', 'post': 'post', 'intermission': 'intermission'}[kind]
    img = art_setting(IMAGE_SLOTS[slot][0])
    pos = (appsettingGet(f'obs_{kind}_title_pos', '') or '').strip().lower()
    return {
        'image': img,
        'image_url': _art_url(img),
        'title': (appsettingGet(f'obs_{kind}_title', '') or '').strip(),
        'pos': pos if pos in TITLE_POSITIONS else 'bottom-center',
    }


MAP_SOURCE_NAME = 'ScenePlay Battle Map'


PANEL_TOKEN_KEY = 'obs-panel'
BG_DIR = os.path.join('static', 'uploads', 'obs')


# ── stream look: accent colour + camera bezel ────────────────────────────────
# One accent runs through every stream page (tile borders, names, titles) so a
# colour change re-skins the whole broadcast, not one corner of it. The bezel
# is the camera tiles' frame shape. Both ride the pages' existing polls, so a
# save re-skins a LIVE stream inside one poll cycle — no source reloads.

DEFAULT_ACCENT = '#c8a86e'          # the gold the pages shipped with
DEFAULT_BASE = '#08090d'            # the near-black every surface tint is cut from
BEZEL_SHAPES = ('rounded', 'square', 'circle', 'hex')
# Gradient directions: CSS linear-gradient angles (the value points TOWARD
# that edge/corner), plus a centred radial glow.
BASE_DIRS = ('0', '45', '90', '135', '180', '225', '270', '315', 'radial')
CARD_DESIGNS = ('classic', 'banner', 'trading')
TILE_DESIGNS = ('strip', 'tag', 'third')
# The DM's badge on cards and tiles. A fixed roster (not free text): these
# render inside OBS's CEF, so every entry is one that build was tested with.
DM_ICONS = ('⚔', '⚙', '🐉', '🎲', '👑',
            '🧙', '🛡', '📜')
THEME_KEYS = ('obs_accent_color', 'obs_base_color', 'obs_base_color2',
              'obs_base_dir', 'obs_bezel_shape',
              'obs_plate_color', 'obs_plate_color2', 'obs_plate_dir',
              'obs_card_design', 'obs_tile_design',
              'obs_dm_icon', 'obs_dm_title')


def theme_accent():
    # art_setting: this session's own value first, else the shared default —
    # the same per-session idiom the show art uses.
    v = art_setting('obs_accent_color')
    return v if re.fullmatch(r'#[0-9a-fA-F]{6}', v) else DEFAULT_ACCENT


def theme_base():
    """The surface colour: panel and title-strip fields, tile strip gradient,
    bezel matte, background fallback. The whole presentation is tinted from
    this one value, so accent + base together are a full colour theme."""
    v = art_setting('obs_base_color')
    return v if re.fullmatch(r'#[0-9a-fA-F]{6}', v) else DEFAULT_BASE


def theme_base2():
    """The far end of the background gradient. Falls back to the BASE colour
    (not a constant): base == base2 renders as today's solid look, so the
    gradient is strictly opt-in."""
    v = art_setting('obs_base_color2')
    return v if re.fullmatch(r'#[0-9a-fA-F]{6}', v) else theme_base()


def theme_base_dir():
    v = art_setting('obs_base_dir').lower()
    return v if v in BASE_DIRS else '180'


def bezel_shape():
    v = art_setting('obs_bezel_shape').lower()
    return v if v in BEZEL_SHAPES else 'rounded'


def theme_plate():
    """The camera tiles' name plate (the strip under the face). Its own pair
    so the plate can contrast the scene; unset, it follows the base pair and
    nothing changes."""
    v = art_setting('obs_plate_color')
    return v if re.fullmatch(r'#[0-9a-fA-F]{6}', v) else theme_base()


def theme_plate2():
    v = art_setting('obs_plate_color2')
    if re.fullmatch(r'#[0-9a-fA-F]{6}', v):
        return v
    # An explicit plate colour without a second one renders solid; no plate
    # at all keeps following the base pair, like theme_plate does.
    v1 = art_setting('obs_plate_color')
    if re.fullmatch(r'#[0-9a-fA-F]{6}', v1):
        return v1
    return theme_base2()


def theme_plate_dir():
    v = art_setting('obs_plate_dir').lower()
    return v if v in BASE_DIRS else '180'


def card_design():
    v = art_setting('obs_card_design').lower()
    return v if v in CARD_DESIGNS else 'classic'


def tile_design():
    """How the camera tiles present the name plate: the full strip, a compact
    name-tag pill, or a broadcast lower-third."""
    v = art_setting('obs_tile_design').lower()
    return v if v in TILE_DESIGNS else 'strip'


def dm_icon():
    v = art_setting('obs_dm_icon')
    return v if v in DM_ICONS else DM_ICONS[0]


def dm_title():
    """What the DM is CALLED on stream — 'Dungeon Master' by default, but a
    sci-fi table runs a GM and Carl's table answers to an AI."""
    return art_setting('obs_dm_title')[:40] or 'Dungeon Master'


def _theme_session_own():
    """Whether the ACTIVE session carries its own look (vs the shared one)."""
    sid = _active_session_id()
    if sid is None:
        return False
    return any((appsettingGet(f'{k}:s{sid}', '') or '').strip()
               for k in THEME_KEYS)


def _theme_payload():
    return {'accent': theme_accent(), 'base': theme_base(),
            'base2': theme_base2(), 'dir': theme_base_dir(),
            'bezel': bezel_shape(),
            'plate': theme_plate(), 'plate2': theme_plate2(),
            'plate_dir': theme_plate_dir(),
            'card': card_design(), 'tile': tile_design(),
            'dm_icon': dm_icon(), 'dm_title': dm_title()}


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


def dice_autohide_on():
    """Dice panel as a pop-over: hidden until a roll lands, gone 5s later."""
    return (appsettingGet('obs_dice_autohide', '1') or '1') == '1'


def _raise_to_front(scene, item_id, warnings):
    """Put one scene item above everything else in its scene.

    Needed by the dice pop-over: the tiles/map now OVERLAP the panel's box,
    and a reused item keeps whatever z-order it had from an older build — so
    without this the panel pops in *behind* the tiles, which reads as the
    feature simply not working."""
    import obs_ws
    try:
        items = obs_ws.request('GetSceneItemList',
                               {'sceneName': scene}).get('sceneItems') or []
        obs_ws.request('SetSceneItemIndex',
                       {'sceneName': scene, 'sceneItemId': item_id,
                        'sceneItemIndex': max(0, len(items) - 1)})
    except (obs_ws.ObsRejected, obs_ws.ObsUnavailable) as exc:
        warnings.append(f'Could not raise the dice panel to the front ({exc}).')


def _frame_areas(canvas_w, canvas_h):
    areas = obs_layout.frame_areas(canvas_w, canvas_h, panel_side(),
                                   panel_fraction(), title_height(), panel_on())
    if panel_on() and dice_autohide_on():
        # Pop-over mode: the panel's column is given BACK to the tiles/map,
        # and the panel box stays where it was — laid on top, transparent
        # until a roll lands. The room is the players' by default; the dice
        # borrow it for five seconds.
        full = obs_layout.frame_areas(canvas_w, canvas_h, panel_side(),
                                      panel_fraction(), title_height(), False)
        areas['tiles'] = full['tiles']
    return areas


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
    if dice_autohide_on():
        # Pop-over dice: the panel's column belongs to the MAP, and the dice
        # box overlays it for five seconds after a roll. Building with the
        # column reserved left the map stuck narrow until a roll cycle
        # finally animated it out — the build must start in the resting
        # state: map full width, dice parked.
        areas = _frame_areas(w, h)
        if areas['panel'] is None:
            # Party panel off entirely: the map's roll feed still needs its
            # box — same forced-on derivation panel_state uses for dice_rect.
            areas['panel'] = obs_layout.frame_areas(
                w, h, panel_side(), panel_fraction(),
                title_height(), True)['panel']
    else:
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
                box = {'x': rect[0], 'y': rect[1],
                       'w': rect[2], 'h': rect[3]}
                if mode == 'dice' and dice_autohide_on():
                    box['x'] = float(w)     # parked off-canvas until a roll
                    _dice_state['shown'] = False
                    _raise_to_front(scene, sid, warnings)
                obs_ws.place_item(scene, sid, box)
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
    # The SAME title strip input the party and map scenes carry, in the same
    # rect, so the campaign banner never jumps when cutting to a card.
    areas = obs_layout.frame_areas(w, h, panel_side(), panel_fraction(),
                                   title_h=title_height(), panel_on=True)
    trect = areas['title']
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
        if trect is not None:
            try:
                tid, warn = obs_ws.ensure_browser_input(
                    scene, TITLE_SOURCE_NAME, panel_url('title'),
                    int(trect[2]), int(trect[3]))
                warnings.extend(warn)
                if tid is not None:
                    obs_ws.place_item(scene, tid,
                                      {'x': trect[0], 'y': trect[1],
                                       'w': trect[2], 'h': trect[3]})
                    obs_ws.set_item_enabled(scene, tid, True)
                    # The card item is full-canvas; a reused strip keeps its
                    # old z-order and would hide behind it.
                    _raise_to_front(scene, tid, warnings)
            except (obs_ws.ObsRejected, obs_ws.ObsUnavailable) as exc:
                warnings.append(f'Could not place the title strip ({exc}).')
        _place_background(scene, w, h, warnings)
        _upsert_special_map(kind, scene)
        scenes[kind] = scene
    obs_ws.scene_list(refresh=True)
    return scenes, warnings


def _source_name_for(char):
    return f'{_scene_name_for(char)} Cam'


def _overlay_source_name_for(char):
    """What ScenePlay draws above a player's camera source: the name strip
    while they are on screen, their stat card while they are not. Shares the
    managed prefix so pruning and the reload-all sweep own it too."""
    return f'{_scene_name_for(char)} Overlay'


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


def _muted_ids():
    """Character ids the DM has muted on the stream.

    Persisted, not just pushed at OBS: builds re-assert every tile's audio
    (_apply_tile_audio), so a mute that lived only inside OBS would silently
    lift on the next Build / refresh — the sort of surprise that gets noticed
    on air."""
    return _id_set('obs_muted_ids')


def _set_muted(character_id, on):
    _set_id_flag('obs_muted_ids', character_id, on)


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

    Display name ONLY — never the login. The login is what someone types into
    the password box, and the overlay goes out on a public stream; an account
    without a display name simply gets no second line."""
    u = getattr(char, 'user', None)
    if not u:
        return ''
    return (getattr(u, 'display_name', '') or '').strip()


def tile_url(character_id):
    # Same reason card_url does this: Flask's <int:> converter never matches a
    # negative number, so the DM tile (id -1) needs its own leaf. Without it
    # the DM's camera tile was a 404 in OBS.
    leaf = 'dm' if character_id == DM_TILE_ID else str(character_id)
    return (f'{_card_base()}{obs_bp.url_prefix}/tile/{leaf}'
            f'?t={_card_token(character_id)}')


def strip_url(character_id):
    """The tile page with the video left out — the name strip alone, on
    transparency, to sit over a camera source."""
    return tile_url(character_id) + '&strip=1'


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
    if char.character_id in _auto_dark_ids:
        # The auto-camera watch saw this feed render black.
        return card_url(char.character_id)
    if presence is None:
        presence = _presence()
    if _feed_state(char, presence) == 'stale':
        # They had a camera and the relay stopped hearing from them.
        return card_url(char.character_id)
    return tile_url(char.character_id)


def _tile_plan(char, presence=None, overrides=None):
    """(url for this player's own source, url for the overlay above it or None).

    Two rules, and the second is what carries the audio:

    The camera cannot be framed by the tile page. OBS loads that page over
    plain http, and an https frame under an http ancestor is not a secure
    context, so WebRTC never starts and the feed is silently black. So the
    SOURCE is the bare feed and ScenePlay's own artwork rides above it as a
    second source.

    And anyone with a feed configured keeps that feed as their source even
    when their stat card is showing — the card is drawn OVER the running
    camera rather than replacing it. Replacing it would tear down the WebRTC
    connection, and with it the player's microphone: pinning someone to their
    card would silence them mid-sentence. Only a player with no feed at all
    has the card as their source, and there is no audio to lose there."""
    if overrides is None:
        overrides = _card_overrides()
    feed = char.video_view_url()
    if not feed:
        return card_url(char.character_id), None
    if presence is None:
        presence = _presence()
    hidden = (char.character_id in overrides
              or char.character_id in _auto_dark_ids
              or _feed_state(char, presence) == 'stale')
    if hidden:
        return feed, card_url(char.character_id, over=True)
    return feed, strip_url(char.character_id)


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
        # Audio last, once EVERY scene exists. It nests the party scene into
        # the others, so running it before they are built silently wires up
        # nothing — which is how a first build after wiping the collection
        # left the table audible only on the party scene.
        snap = obs_ws.current_state()
        _build_audio(snap.get('base_width') or 1920,
                     snap.get('base_height') or 1080, result['warnings'])
        # Read back what OBS ACTUALLY holds, rather than what we believe we
        # sent. A source that silently fails to land is otherwise invisible
        # from here — the build reports success and the scene is missing a
        # piece with nothing to say so.
        result['contents'] = _scene_inventory(
            [result['scene'], map_scene] + sorted(show_scenes.values()))
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


def _apply_tile_audio(source, char, warnings):
    """Put one camera source's audio where the DM asked for it.

    Two separate questions, and OBS answers them with different calls:

    MUTE decides whether the source reaches the stream at all. The DM's own
    tile is muted by default — it is their own microphone coming back at them,
    which is an echo on the broadcast and, if they are monitoring, feedback in
    the room. Their real mic is already an OBS input.

    MONITORING decides whether the DM hears it locally. Off by default because
    most tables are already on a voice call and would hear everyone twice;
    turn it on when these feeds are the only way the DM hears their players.
    A build with no monitoring device configured rejects this, which is not
    worth failing a scene build over."""
    import obs_ws
    is_dm = char.character_id == DM_TILE_ID
    muted = (char.character_id in _muted_ids()
             or (is_dm and not _dm_audio_on()))
    try:
        obs_ws.set_input_mute(source, muted)
    except (obs_ws.ObsRejected, obs_ws.ObsUnavailable) as exc:
        warnings.append(f'Could not set the audio for {char.name} ({exc}).')
        return
    try:
        obs_ws.set_audio_monitor(
            source,
            obs_ws.MONITOR_ROOM if _feed_monitor_on() else obs_ws.MONITOR_OFF)
    except (obs_ws.ObsRejected, obs_ws.ObsUnavailable):
        # No monitoring device set up in OBS. The feed still reaches the
        # stream; only the DM's own speakers miss out.
        log.info('OBS would not set monitoring for %s', source)


def _dm_audio_on():
    """Does the DM's own camera tile carry audio into OBS?"""
    return (appsettingGet('obs_dm_audio', '0') or '0') == '1'


def _feed_monitor_on():
    """Does OBS play the player feeds out loud in the DM's room?"""
    return (appsettingGet('obs_feed_monitor', '0') or '0') == '1'


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
    strips = set()
    for char, rect in zip(members, rects):
        source = _source_name_for(char)
        url, overlay = _tile_plan(char, presence, overrides)
        _tile_urls[char.character_id] = (url, overlay)
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
        # Only a source actually pointed at a feed carries sound; a card is a
        # silent web page and needs no mixer treatment.
        if overlay is not None:
            _apply_tile_audio(source, char, warnings)
        _upsert_player_map(char.character_id, scene, source, auto_created=1)
        placed.append({'character_id': char.character_id, 'name': char.name,
                       'source': source, 'item_id': item_id,
                       'featured': rect['featured']})

        # The overlay rides in the SAME box, one layer up: the name strip over
        # a visible camera, the opaque stat card over a hidden one. A player
        # with no feed at all has no overlay — their source IS the card.
        if overlay is None:
            continue
        overlay_source = _overlay_source_name_for(char)
        s_item = _ensure_input(scene, overlay_source, overlay,
                               render_w, render_h, warnings)
        if s_item is None:
            continue
        strips.add(overlay_source)
        if anim_ms and was and was != target:
            moves.append((s_item, was, target))
        else:
            obs_ws.place_item(scene, s_item, rect)
        obs_ws.set_item_enabled(scene, s_item, True)

    # Kicked off before the panel/background work below so the move starts
    # while those requests are still going out — it runs on its own thread.
    if moves:
        obs_ws.animate_items(scene, moves, duration_s=anim_ms / 1000.0)

    # Someone who left the party must not leave a stale rect behind: if they
    # come back their tile would ease in from wherever it used to sit.
    live_ids = {p['character_id'] for p in placed}
    for gone in [cid for cid in _tile_rects if cid not in live_ids]:
        _tile_rects.pop(gone, None)

    keep = {p['source'] for p in placed} | strips

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
                box = {'x': rect[0], 'y': rect[1],
                       'w': rect[2], 'h': rect[3]}
                if mode == 'info' and dice_autohide_on():
                    # Reflow mode: the panel waits OFF-CANVAS until a roll
                    # slides it in. Parked, not hidden, so the slide is a
                    # move of a live source rather than a pop-in.
                    box['x'] = float(canvas_w)
                    _dice_state['shown'] = False
                    _raise_to_front(scene, item_id, warnings)
                obs_ws.place_item(scene, item_id, box)
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
    # NOT _build_audio here. It nests the party scene into the map and show
    # scenes, and those are created AFTER this function returns — so on a
    # first build (or the first after the DM wipes their collection) they do
    # not exist yet, nothing gets nested, and the table goes silent the moment
    # the program cuts away from the party. api_build_party calls it once the
    # whole set is present. Featuring a player comes through here too, and has
    # no business re-wiring audio.
    obs_ws.scene_list(refresh=True)
    return {'scene': scene, 'tiles': placed, 'warnings': warnings,
            'featured_id': featured_id}


def _scene_inventory(scene_names):
    """{scene: [description, ...]} straight from OBS, for the build report.

    Reports each item's ENABLED state and its box, not just its name: a source
    that is present but hidden, off-canvas or zero-sized looks identical to a
    working one in a bare name list, and those are exactly the states that
    make a scene "missing" something the build swears it placed."""
    import obs_ws
    out = {}
    for name in scene_names:
        if not name or name in out:
            continue
        try:
            lst = obs_ws.request('GetSceneItemList', {'sceneName': name})
            rows = []
            for it in sorted(lst.get('sceneItems') or [],
                             key=lambda i: i.get('sceneItemIndex', 0)):
                src = it.get('sourceName', '?')
                bits = [src]
                if not it.get('sceneItemEnabled', True):
                    bits.append('HIDDEN')
                try:
                    tr = obs_ws.request('GetSceneItemTransform', {
                        'sceneName': name,
                        'sceneItemId': it.get('sceneItemId')})['sceneItemTransform']
                    w = round(tr.get('boundsWidth') or tr.get('width') or 0)
                    h = round(tr.get('boundsHeight') or tr.get('height') or 0)
                    bits.append(f'@{round(tr.get("positionX", 0))},'
                                f'{round(tr.get("positionY", 0))} {w}x{h}')
                    if w < 2 or h < 2:
                        bits.append('ZERO SIZE')
                except (obs_ws.ObsRejected, obs_ws.ObsUnavailable):
                    pass
                # What the source is ACTUALLY pointed at. A tile still on
                # /card/ after its owner was un-pinned, or a source left on an
                # old host, both look perfect in a name-and-box listing.
                try:
                    st = obs_ws.request('GetInputSettings',
                                        {'inputName': src})['inputSettings']
                    u = str(st.get('url') or '')
                    if u:
                        # Drop the capability token: this text gets pasted into
                        # chats and screenshots.
                        u = re.sub(r'([?&]t=)[^&]*', r'\1<token>', u)
                        bits.append(u)
                except (obs_ws.ObsRejected, obs_ws.ObsUnavailable, KeyError):
                    pass
                rows.append('  '.join(bits))
            out[name] = rows
        except (obs_ws.ObsRejected, obs_ws.ObsUnavailable) as exc:
            out[name] = [f'(could not read: {exc})']
    return out


# Legacy: sound used to ride in a scene of its own. The party scene carries it
# now — this name survives only so a build can clear the old one away.
AUDIO_SCENE_NAME = 'ScenePlay Audio'
MUSIC_SOURCE_NAME = 'ScenePlay Music'


MUSIC_FEED_SOURCE_NAME = 'ScenePlay Music Feed'
MUSIC_TRANSPORTS = ('auto', 'device', 'feed', 'off')
DEFAULT_MUSIC_LABEL = 'ScenePlay-Music'    # relay_audio_stream.SOURCE_LABEL


def music_capture_on():
    return (appsettingGet('obs_music_capture', '1') or '1') == '1'


def music_device_label():
    """The audio input vdo.ninja should grab, matched on its LABEL.

    Defaults to the null sink's description, which the browser lists as
    "Monitor of ScenePlay-Stream" — distinctive enough to match safely. The
    real microphone is NOT safe to match this way on a typical box: its label
    usually appears twice, once as the input and once as "Monitor of ..." the
    output, and picking the monitor would capture the speakers, players and
    all."""
    return ((appsettingGet('obs_music_device_label', '') or '').strip()
            or DEFAULT_MUSIC_LABEL)


def music_cable_platform():
    """Does the machine playing the music need a virtual cable to publish it?

    Windows does: it has no null sink to build and no monitor source, so the
    vdo.ninja push tab can only capture a real recording device. Asked as its
    own question so the page and the warnings agree, and so a test can put
    either platform in front of them."""
    return os.name == 'nt'


def music_output_device():
    """The device the music player plays INTO on this machine (mpv's
    --audio-device), or '' for whatever Windows/mpv picks by default.

    Only meaningful on Windows. Linux builds the capture sink itself and mpv
    is pointed at it automatically; Windows has no sink to build, so the feed
    path needs a virtual cable the DM installs and names here. See
    relay_audio_stream.win_device."""
    return (appsettingGet('music_output_device', '') or '').strip()


_MPV_DEVICES = {'at': 0.0, 'list': []}
_MPV_DEVICES_TTL = 60      # a cable is installed once; re-probing per render
                           # spawns mpv on every Broadcast poll for nothing


def music_output_choices(refresh=False):
    """Audio outputs mpv can actually play into on this machine.

    Asked of mpv rather than of Windows: the id in the box IS an mpv
    --audio-device value, and mpv's WASAPI ids are opaque GUIDs. Typing one
    correctly from a Windows sound panel is not something to ask of anyone, so
    the page offers the list mpv itself prints.

    Returns [(device_id, human label)], default-output first. Empty list of
    devices (no mpv on PATH, probe failed) still yields that first entry, so
    the control degrades to "default output" rather than vanishing.

    Never probes on a platform with no cable to pick: Linux builds its own
    sink and hides this control entirely, so spawning mpv there would be a
    subprocess per render feeding a dropdown nobody sees."""
    import subprocess
    out = [('', 'Default output device')]
    if not music_cable_platform():
        return out
    if refresh or (time.time() - _MPV_DEVICES['at']) > _MPV_DEVICES_TTL:
        found = []
        try:
            res = subprocess.run(
                ['mpv', '--audio-device=help'], capture_output=True,
                text=True, timeout=8,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            for line in (res.stdout or '').splitlines():
                m = re.match(r"\s*'([^']+)'\s+\((.*)\)\s*$", line)
                # 'auto' is mpv's own default pick — the blank entry above
                # already means that, and two ways to say it read as two
                # different choices.
                if m and m.group(1) != 'auto':
                    label = m.group(2)
                    # VB-CABLE ships two near-twin playback ends: "CABLE
                    # Input" (stereo, pairs with the "CABLE Output" the feed
                    # captures) and "CABLE In 16ch" (multichannel; what goes
                    # in there does not arrive at the stereo output). Four
                    # characters apart in a dropdown, and picking the wrong
                    # one is a silent dead feed — say so on the option
                    # itself, where the choice is being made.
                    if re.search(r'CABLE In 16\s*ch', label, re.I):
                        label += ' — wrong end for the feed; use "CABLE Input"'
                    found.append((m.group(1), label))
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            log.info('Could not list mpv audio devices: %s', exc)
        # A failed probe keeps the last good list rather than emptying the
        # box: the DM's chosen cable would otherwise disappear from the select
        # mid-session and the next autosave would write it away as "default".
        if found:
            _MPV_DEVICES['list'] = found
        _MPV_DEVICES['at'] = time.time()
    return out + list(_MPV_DEVICES['list'])


_CAPTURE_DEVICES = {'at': 0.0, 'list': []}


def music_capture_choices(refresh=False):
    """Capture-device labels this machine could offer the vdo.ninja push tab —
    suggestions for the "device vdo.ninja should send" box, not a closed list.

    The box stays free text because the MATCH happens in the browser, against
    whatever labels IT enumerates; this list exists so the DM picks the right
    device instead of transcribing it. Each platform is asked in its own
    language: Windows via ffmpeg's DirectShow enumeration (ffmpeg already
    ships with the relay), Linux via pactl's source descriptions — the labels
    a browser shows — with the app-built ScenePlay-Music source pinned first,
    because it is the one right answer there. Monitor sources are left out:
    "Monitor of <your speakers>" would capture the players and loop them
    back, and the safe monitor carries the same audio as ScenePlay-Music.
    Cached and kept-on-failure like the mpv probe; a machine with neither
    enumerator (macOS) gets no suggestions rather than wrong ones."""
    import shutil
    import subprocess
    if not music_cable_platform() and not shutil.which('pactl'):
        return []
    if refresh or (time.time() - _CAPTURE_DEVICES['at']) > _MPV_DEVICES_TTL:
        found = []
        try:
            if music_cable_platform():
                res = subprocess.run(
                    ['ffmpeg', '-hide_banner', '-list_devices', 'true',
                     '-f', 'dshow', '-i', 'dummy'],
                    capture_output=True, text=True, timeout=8,
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                # The list rides on stderr (the "input" itself fails, by
                # design), one device per line: "Name" (audio)
                for line in ((res.stderr or '')
                             + (res.stdout or '')).splitlines():
                    m = re.search(r'"([^"]+)"\s+\(audio\)\s*$', line)
                    if m:
                        found.append(m.group(1))
            else:
                # The default label leads even if the probe finds nothing:
                # the remap source only exists once music has played, and
                # the DM configures this page before pressing play.
                found.append(DEFAULT_MUSIC_LABEL)
                res = subprocess.run(
                    ['pactl', 'list', 'sources'],
                    capture_output=True, text=True, timeout=8)
                for line in (res.stdout or '').splitlines():
                    m = re.match(r'\s*Description:\s*(.+?)\s*$', line)
                    if m:
                        lbl = m.group(1)
                        if (lbl != DEFAULT_MUSIC_LABEL
                                and not lbl.startswith('Monitor of ')):
                            found.append(lbl)
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            log.info('Could not list capture devices: %s', exc)
            # A failed probe keeps the last good list; with nothing to keep,
            # the seeded default (Linux) still makes it into the box.
            if _CAPTURE_DEVICES['list']:
                found = []
        if found:
            _CAPTURE_DEVICES['list'] = found
        _CAPTURE_DEVICES['at'] = time.time()
    return list(_CAPTURE_DEVICES['list'])


def music_output_options():
    """The choices the page shows, with the DM's saved device guaranteed to be
    among them.

    A device missing from the probe (mpv absent, cable unplugged, USB
    interface asleep) would otherwise leave the select sitting on "default" —
    and the page autosaves, so simply LOOKING at it would erase the setting
    and take the music off the cable."""
    chosen = music_output_device()
    opts = music_output_choices()
    if chosen and not any(dev == chosen for dev, _lbl in opts):
        opts.append((chosen, chosen + ' — saved, not detected right now'))
    return opts


def music_label_options():
    """The choices the vdo.ninja label select shows, with the saved label
    guaranteed among them — same autosave trap as music_output_options: a
    saved label the probe misses would leave the select on its first entry,
    and merely opening the page would save that entry back.

    A select, not free text, since music_capture_choices learned to answer
    per-platform: each machine now lists its own right devices, and the match
    string no longer needs to be typable from memory."""
    chosen = music_device_label()
    opts = [(lbl, lbl) for lbl in music_capture_choices()]
    if not any(val == chosen for val, _lbl in opts):
        opts.append((chosen, chosen + ' — saved, not detected right now'))
    return opts


def repush_feeds(reason=''):
    """Tell the relay portal that the camera links changed.

    The links are built HERE — ScenePlay owns the vdo.ninja base, the params,
    the password and the room — and the relay only carries the finished string.
    So a room the portal never hears about is worse than a broken link: the old
    one still WORKS, it just joins a room nobody else is in, and the player
    sits there able to see themselves and hear no one.

    Queued and coalesced by the broadcaster, so this never blocks the request,
    and silent when the relay is off — which is the normal case."""
    try:
        import relay_broadcaster
        relay_broadcaster.push_character_feeds()
    except Exception as exc:                 # relay off, absent, or failing
        log.info('Camera-link re-push skipped (%s): %s', reason, exc)


def _room_bitrate_str():
    from models.ttrpg import _room_videobitrate
    return str(_room_videobitrate())


def table_room():
    """The vdo.ninja room the whole table shares, or '' when there isn't one."""
    return (appsettingGet('obs_vdo_room', '') or '').strip()


# vdo.ninja rejects a room name that is not alphanumeric or runs past 30
# characters — and it rejects it at the GUEST, so a bad name looks like the
# player's link being broken rather than a setting being wrong.
ROOM_MAX = 30


def clean_room(name):
    """A room name vdo.ninja will actually accept: alphanumeric, <= 30."""
    return re.sub(r'[^A-Za-z0-9]', '', (name or '').strip())[:ROOM_MAX]


def _new_room_name():
    """A fresh room name: a GUID, trimmed to what vdo.ninja allows.

    Random rather than readable, because the name IS the way in. vdo.ninja
    rooms are created simply by being joined, so anyone who guesses
    'dungeoncrawler' walks into the session — camera, microphone and all.

    Hex, so it is alphanumeric with no hyphens to be rejected or mangled in a
    URL, and cut to 30 characters. That still leaves ~120 bits of randomness,
    which is not a number anyone guesses."""
    return uuid.uuid4().hex[:ROOM_MAX]


@obs_bp.route('/api/room/new', methods=['POST'])
@login_required
@dm_required
def api_new_room():
    """Create the table's room. Every push link picks it up immediately —
    players and the DM alike — so the only thing left is for people to reopen
    their camera page."""
    room = _new_room_name()
    appsettingSet('obs_vdo_room', room)
    repush_feeds('new room')
    return jsonify({'ok': True, 'room': room,
                    'join_url': dm_tile().video_push_url()})


def music_stream_id():
    """The DM's music push id, minted once and then kept."""
    sid = (appsettingGet('obs_music_stream_id', '') or '').strip()
    if not sid:
        sid = _new_stream_id()
        appsettingSet('obs_music_stream_id', sid)
    return sid


def _music_vdo_url(kind):
    """Build the music push/view URL.

    Deliberately NOT models._vdo_url: this stream carries music, not a person,
    so it wants &proaudio (stereo, high bitrate, and crucially no echo
    cancellation / denoise / auto-gain, which mangle music) and it must stay
    OUT of the table's room — players already get the music through the portal
    and would otherwise hear it twice."""
    from urllib.parse import quote
    from models.ttrpg import VDO_DEFAULTS
    base = ((appsettingGet('obs_vdo_base', '') or '').strip()
            or VDO_DEFAULTS['obs_vdo_base'])
    if not base.endswith('/'):
        base += '/'
    sid = quote(music_stream_id(), safe='')
    if kind == 'push':
        # &videodevice=0: audio only. Without it, &autostart also switches on
        # the machine's default webcam — the page promises "no camera", and
        # the DM's camera already reaches the stream through their tile.
        url = (f'{base}?push={sid}&proaudio&autostart&videodevice=0'
               f'&audiodevice={quote(music_device_label(), safe="")}')
    else:
        url = f'{base}?view={sid}&proaudio&cleanoutput&transparent&autostart'
    password = (appsettingGet('obs_vdo_password', '') or '').strip()
    if password:
        url += '&password=' + quote(password, safe='')
    return url


def music_push_url():
    """What the DM opens on the machine playing the music."""
    return _music_vdo_url('push')


def music_view_url():
    return _music_vdo_url('view')


def obs_is_local():
    """Is OBS on this same machine? Decides whether a local audio device can
    be captured at all."""
    host = (appsettingGet('obs_host', '') or '').strip().lower()
    if host in ('', '127.0.0.1', 'localhost', '::1', '[::1]'):
        return True
    return host == (urlsplit(lan_base()).hostname or '').lower()


def obs_platform():
    import obs_ws
    return (obs_ws.current_state().get('obs_platform') or '').lower()


def can_capture_music_device():
    """Could THIS OBS capture the music sink directly?

    Asked as a capability, never as a platform name. OBS reports its distro —
    this box answers "Freedesktop SDK 25.08 (Flatpak runtime)", with no
    "Linux" in it anywhere — so matching on the name sent the one machine that
    CAN capture the sink down the vdo.ninja path instead.

    The sink is a PulseAudio/PipeWire device, so the real question is whether
    OBS offers a PulseAudio output capture at all. A macOS or Windows OBS
    offers coreaudio/wasapi instead and could never see this sink, even when
    it happens to be running on the same host."""
    import obs_ws
    return obs_ws.audio_capture_kind() == 'pulse_output_capture'


MUSIC_WHY = {
    'device': 'OBS is on this machine and can read the music sink directly — '
              'no stream, no extra tab, no delay.',
    'feed':   'OBS cannot reach this machine\'s audio devices, so the music '
              'travels to it as a vdo.ninja stream.',
    'off':    'Music is not being sent to OBS at all.',
}


def rig_summary():
    """Where OBS is running, and everything that follows from it.

    Written because the consequences were scattered: the page address lives in
    one card, the music path in another, and the macOS limitation only ever
    appeared as a build warning after the fact. Each one is invisible until it
    silently produces a blank source or a dead channel, and every one of them
    is decided by the same question — is OBS on this machine or another?"""
    import obs_ws
    local = obs_is_local()
    platform = (obs_ws.current_state().get('obs_platform') or '').strip()
    is_mac = ('mac' in platform.lower() or 'darwin' in platform.lower())
    transport = music_transport()
    base = _card_base()

    problems, steps = [], []
    # The single most common invisible failure: OBS connects over the
    # websocket perfectly and then renders every source blank.
    if not local and is_loopback_base(base):
        problems.append(
            f'The page address is {base} — a loopback address. OBS is on '
            f'another machine, where that means ITS own machine, so every '
            f'ScenePlay source will render blank. Use {lan_base()}.')
    if is_mac:
        problems.append(
            'This OBS runs on macOS, which carries no browser-source audio at '
            'all (measured). Player voices and the music feed will be silent '
            'here however they are configured; only OBS\'s own inputs have '
            'sound.')
    # A custom feed URL is a link ScenePlay does not build, so the room never
    # gets added to it. That player publishes outside the room: they hear
    # nobody, nobody hears them, and their OBS tile stays black — while their
    # own camera page looks perfectly fine to them.
    if table_room():
        try:
            outside = [c.name for c in _active_party()
                       if (c.video_feed_url or '').strip()]
        except Exception:
            outside = []
        if outside:
            problems.append(
                'Outside the table room, because they use a custom feed URL '
                'ScenePlay cannot add the room to: ' + ', '.join(outside) +
                '. Clear the custom URL on their camera page to bring them in.')
    # The feed's publishing half, which lives on THIS machine and is invisible
    # from OBS: the source there is created, unmuted and correct whether or not
    # anything is being published into it. On Windows both halves of the cable
    # have to be named, and neither has a default that works — the shipped
    # label is a PulseAudio device that exists on Linux only.
    if transport == 'feed' and music_cable_platform():
        if not music_output_device():
            problems.append(
                'The music player is not playing into a virtual cable, so the '
                'feed has nothing to send. Windows has no capture sink: pick '
                'the cable\'s INPUT under "Music output device" below (install '
                'VB-CABLE first if the list has none), and tick "Listen to '
                'this device" on its output in Windows Sound so you still '
                'hear the music yourself.')
        if music_device_label() == DEFAULT_MUSIC_LABEL:
            problems.append(
                f'The feed is set to send "{DEFAULT_MUSIC_LABEL}", which is a '
                f'Linux-only device and does not exist on this machine — the '
                f'browser matches nothing and publishes silence. Use the '
                f'cable\'s OUTPUT instead (e.g. "CABLE Output").')
    if transport == 'feed':
        steps.append('Open the music feed on the machine playing the music '
                     'and leave the tab running.')
    if not local:
        # Never quote a loopback base here: the problem above is already
        # telling them to change it, and repeating it as the address to keep
        # reachable is advice that contradicts itself.
        reach = lan_base() if is_loopback_base(base) else base
        steps.append('Player camera tiles load ScenePlay pages over the LAN, '
                     'so this machine must stay reachable at ' + reach + '.')
    return {
        'local': local,
        'where': 'This machine' if local else 'Another machine',
        'host': (appsettingGet('obs_host', '') or '').strip() or '127.0.0.1',
        'platform': platform,
        'transport': transport,
        'music_why': MUSIC_WHY.get(transport, ''),
        'problems': problems,
        'steps': steps,
    }


def music_transport():
    """How the music should reach OBS: 'device', 'feed', or 'off'.

    'auto' monitors the sink directly when OBS is on this machine and able to
    read it, and streams it as a vdo.ninja feed otherwise. Local and remote
    rigs therefore need no different setup — the same build does the right
    thing for whichever OBS is currently connected."""
    want = (appsettingGet('obs_music_transport', 'auto') or 'auto').strip()
    if want not in MUSIC_TRANSPORTS:
        want = 'auto'
    if want != 'auto':
        return want
    if not music_capture_on():
        return 'off'
    if obs_is_local() and can_capture_music_device():
        return 'device'
    return 'feed'


def music_device_id():
    """The monitor of the null sink mpv already plays into.

    Capturing THAT rather than the desktop is what keeps this safe: the sink
    carries the music and nothing else, so it cannot pick up the players'
    voices coming back out of OBS's monitoring and turn them into a loop."""
    default = 'sceneplay_music'
    try:
        from relay_audio_stream import SINK_NAME
        default = SINK_NAME
    except Exception:
        pass
    return ((appsettingGet('obs_music_device', '') or '').strip()
            or f'{default}.monitor')


def _scenes_in_obs():
    """The ScenePlay scenes that actually exist right now, party first."""
    import obs_ws
    try:
        known, _cur = obs_ws.scene_list(refresh=True)
    except (obs_ws.ObsRejected, obs_ws.ObsUnavailable):
        return []
    names = {s if isinstance(s, str) else s.get('sceneName') for s in known}
    want = [_cut_scene_name(k) for k in
            ('party', 'map', 'pre', 'intermission', 'post')]
    out = []
    for n in want:                       # dedupe, keep order, skip missing
        if n in names and n not in out:
            out.append(n)
    return out


def _build_audio(canvas_w, canvas_h, warnings):
    """Carry the table's sound into every scene.

    OBS renders a source's audio only while that source is in the CURRENT
    scene — global mic/desktop devices are the sole exception. The cameras
    live in the party scene, so cutting to the battle map used to take every
    player's voice with it, mid-sentence.

    The party scene ITSELF is nested into each of the other scenes and parked
    off-canvas. A nested scene's inputs are live whenever the parent is on
    program, and position has no bearing on audio, so every voice and the
    music carry across a cut while drawing nothing. One source of truth:
    whoever can be heard in the party scene can be heard everywhere, with no
    second membership list to fall out of step.

    The trade, chosen deliberately: OBS composites the whole party scene into
    a texture it then throws away, and if that off-canvas transform is ever
    lost the party layout lands on top of whatever scene it is nested in. The
    next build puts it back."""
    import obs_ws
    scenes = _scenes_in_obs()
    if not scenes:
        return
    party = party_scene_name()

    transport = music_transport()
    if 'mac' in obs_platform() or 'darwin' in obs_platform():
        warnings.append(
            'This OBS runs on macOS, where obs-browser carries no browser '
            'source audio at all — measured. Player voices and any vdo.ninja '
            'music feed will be silent on this machine whatever is set here.')
    _place_music(party, transport, canvas_w, warnings)
    if transport == 'device':
        _warn_if_music_doubled(warnings)
    _mute_machine_mics(warnings)

    _drop_legacy_audio_scene(warnings)

    for sc in scenes:
        if sc == party:
            continue        # a scene cannot contain itself
        try:
            item = obs_ws.ensure_nested_scene(sc, party)
            if item is not None:
                # Off-canvas: heard, never seen.
                obs_ws.place_item(sc, item, {'x': int(canvas_w) + 100, 'y': 0,
                                             'w': 320, 'h': 180})
                obs_ws.set_item_enabled(sc, item, True)
        except (obs_ws.ObsRejected, obs_ws.ObsUnavailable) as exc:
            warnings.append(f'Could not carry the audio into "{sc}" ({exc}).')


def _place_music(party, transport, canvas_w, warnings):
    """Put exactly ONE music source in the party scene, and clear the other.

    Leaving both behind would either double the music or leave a dead source
    that looks correct and plays nothing — the failure this whole integration
    keeps producing."""
    import obs_ws
    stale = {'device': MUSIC_FEED_SOURCE_NAME,
             'feed': MUSIC_SOURCE_NAME}.get(transport)
    if transport == 'off':
        stale = None
    try:
        items = obs_ws.scene_items(party)
    except (obs_ws.ObsRejected, obs_ws.ObsUnavailable):
        items = {}
    for name in ([stale] if stale else [MUSIC_SOURCE_NAME,
                                        MUSIC_FEED_SOURCE_NAME]):
        if name in items:
            try:
                obs_ws.remove_item(party, items[name])
            except (obs_ws.ObsRejected, obs_ws.ObsUnavailable):
                pass

    if transport == 'device':
        device = music_device_id()
        try:
            obs_ws.ensure_audio_input(party, MUSIC_SOURCE_NAME, device)
        except (obs_ws.ObsRejected, obs_ws.ObsUnavailable) as exc:
            warnings.append(
                f'Could not capture the music into OBS ({exc}). Expected an '
                f'audio device named "{device}" — it exists only on the '
                f'machine running the music, and only while it is playing.')
    elif transport == 'feed':
        try:
            item = _ensure_input(party, MUSIC_FEED_SOURCE_NAME,
                                 music_view_url(), 320, 180, warnings)
            if item is not None:
                # Audio only — parked off-canvas so its blank frame never
                # lands on the layout.
                obs_ws.place_item(party, item, {'x': int(canvas_w) + 100,
                                                'y': 0, 'w': 320, 'h': 180})
                obs_ws.set_item_enabled(party, item, True)
        except (obs_ws.ObsRejected, obs_ws.ObsUnavailable) as exc:
            warnings.append(f'Could not add the music feed ({exc}).')


def _drop_legacy_audio_scene(warnings):
    """Undo the earlier arrangement: a separate 'ScenePlay Audio' scene, and a
    music capture in every scene rather than only the party's.

    Both would now be the same inputs active twice over — the nested party
    scene already carries them."""
    import obs_ws
    party = party_scene_name()
    try:
        known, _cur = obs_ws.scene_list(refresh=True)
    except (obs_ws.ObsRejected, obs_ws.ObsUnavailable):
        return
    names = [s if isinstance(s, str) else s.get('sceneName') for s in known]
    for sc in names:
        if not sc or sc == AUDIO_SCENE_NAME:
            continue
        try:
            items = obs_ws.scene_items(sc)
        except (obs_ws.ObsRejected, obs_ws.ObsUnavailable):
            continue
        stale = [AUDIO_SCENE_NAME]
        if sc != party:
            stale.append(MUSIC_SOURCE_NAME)
        for src in stale:
            if src in items:
                try:
                    obs_ws.remove_item(sc, items[src])
                except (obs_ws.ObsRejected, obs_ws.ObsUnavailable):
                    pass
    if AUDIO_SCENE_NAME in names:
        try:
            obs_ws.request('RemoveScene', {'sceneName': AUDIO_SCENE_NAME})
        except (obs_ws.ObsRejected, obs_ws.ObsUnavailable) as exc:
            warnings.append(f'Could not remove the old audio scene ({exc}).')


def _mute_machine_mics(warnings):
    """Mute OBS's own global microphone inputs when the DM's voice already
    arrives through their camera tile.

    OBS adds a Mic/Aux input on its machine by default, and a global device is
    live in EVERY scene — so working anywhere near the OBS box puts the DM on
    the stream twice: once clean through the tile, once roomy and delayed
    through the machine's mic. On a remote rig nobody even remembers that mic
    exists.

    Only when the tile carries the DM (obs_dm_audio on): with tile audio OFF
    the machine's mic may be the DM's one real voice path — the classic
    local-OBS setup — and muting it would silence them entirely. Mute only,
    never unmute: a DM who deliberately opened that mic gets to keep it by
    unmuting it again, and the build note says which channel was touched."""
    import obs_ws
    if not _dm_audio_on():
        return
    try:
        special = obs_ws.request('GetSpecialInputs')
    except (obs_ws.ObsRejected, obs_ws.ObsUnavailable):
        return
    for key in ('mic1', 'mic2', 'mic3', 'mic4'):
        name = special.get(key)
        if not name:
            continue
        # REMOVE rather than mute. Muting silences the mix but OBS keeps the
        # device captured — the meter goes on flickering and macOS keeps its
        # orange mic-in-use dot lit, which reads as "still recording me"
        # because, at the hardware level, it is. Removal is what OBS's own
        # Settings → Audio → Disabled does, and putting it back is that same
        # dropdown.
        try:
            obs_ws.request('RemoveInput', {'inputName': name})
            warnings.append(
                f'Removed OBS\'s own "{name}" input: your voice already '
                f'reaches the stream through your camera tile, so that mic '
                f'could only double you. Re-enable it in OBS under Settings '
                f'→ Audio if you ever want it back.')
        except (obs_ws.ObsRejected, obs_ws.ObsUnavailable):
            # Couldn't remove — at least keep it out of the mix.
            try:
                if obs_ws.request('GetInputMute',
                                  {'inputName': name})['inputMuted']:
                    continue
                obs_ws.set_input_mute(name, True)
                warnings.append(
                    f'Muted OBS\'s own "{name}" input (removal was refused). '
                    f'It stays captured but contributes nothing to the '
                    f'stream.')
            except (obs_ws.ObsRejected, obs_ws.ObsUnavailable):
                continue


def _warn_if_music_doubled(warnings):
    """Desktop Audio also hears the music, because the music sink is looped
    back to the GM's speakers so they can hear it too. Capturing both puts it
    in the stream twice, slightly out of phase."""
    import obs_ws
    try:
        special = obs_ws.request('GetSpecialInputs')
    except (obs_ws.ObsRejected, obs_ws.ObsUnavailable):
        return
    for key in ('desktop1', 'desktop2'):
        name = special.get(key)
        if not name:
            continue
        try:
            if obs_ws.request('GetInputMute',
                              {'inputName': name})['inputMuted']:
                continue
        except (obs_ws.ObsRejected, obs_ws.ObsUnavailable):
            continue
        warnings.append(
            f'"{name}" is also capturing this machine\'s audio, so the music '
            f'may reach the stream twice. Mute it in the Audio Mixer, or '
            f'untick "Capture the music into OBS".')
        return


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
            # Custom feed URLs are no longer accepted from anywhere. ScenePlay
            # builds the link so it can put the table's ROOM in it; a pasted
            # link has none, which drops that person out of the room silently —
            # they see themselves, hear nobody, and their tile is black.
            appsettingSet('obs_dm_feed_url', '')
            if not appsettingGet('obs_dm_stream_id', ''):
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
        # No custom URLs, from here or anywhere else — see dm_feed. Clearing on
        # save also walks any player still holding an old one back into the
        # room the next time they touch this page.
        char.video_feed_url = ''
        if not char.video_stream_id:
            char.video_stream_id = _new_stream_id()
        flash('Camera settings saved.')
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

def token_ok(given, expected):
    """Constant-time token compare that cannot crash the request.

    hmac.compare_digest raises TypeError on strings holding non-ASCII, so a
    URL carrying, say, a pasted ellipsis turned a wrong token into a 500
    instead of a clean 403. Comparing the UTF-8 bytes keeps it constant-time
    and makes every bad token look the same to the caller."""
    import hmac
    try:
        return hmac.compare_digest((given or '').encode('utf-8', 'replace'),
                                   (expected or '').encode('utf-8', 'replace'))
    except (TypeError, ValueError):
        return False


def _card_token(character_id):
    import hashlib
    import hmac
    key = (current_app.secret_key or '').encode() or b'sceneplay'
    return hmac.new(key, f'obs-card:{character_id}'.encode(),
                    hashlib.sha256).hexdigest()[:32]


DEFAULT_CARD_PORT = 8086          # the port ws.py serves ScenePlay on


def lan_base():
    """This machine's LAN address, as a browser-source base URL.

    Found by opening a UDP socket toward a public address and reading back
    which local interface the OS picked — no packet is actually sent. Falls
    back to the hostname, then to loopback."""
    import socket
    ip = ''
    try:
        sk = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sk.connect(('8.8.8.8', 80))
            ip = sk.getsockname()[0]
        finally:
            sk.close()
    except OSError:
        ip = ''
    if not ip or ip.startswith('127.'):
        try:
            ip = socket.gethostbyname(socket.gethostname())
        except OSError:
            ip = ''
    return f'http://{ip or "127.0.0.1"}:{DEFAULT_CARD_PORT}'


def suggested_card_base():
    """The best guess at an address OBS can fetch ScenePlay from.

    Prefers the address the DM's own browser is using, because it carries the
    real port — lan_base() can only assume the default one. Falls back to the
    LAN sniff when the DM is on loopback, since baking in localhost would work
    here and render blank on any other machine."""
    try:
        here = request.host_url.rstrip('/')
    except RuntimeError:            # no request context (background thread)
        return lan_base()
    return lan_base() if is_loopback_base(here) else here


def card_base_stale():
    """Has the saved address stopped being this machine?

    Only judged for a bare IPv4 literal: a hostname or an mDNS name may still
    resolve perfectly well and must not be nagged about. A DHCP lease moving
    this box to a new address is otherwise invisible — OBS keeps connecting
    over the websocket and every source quietly renders nothing."""
    base = (appsettingGet('obs_card_base', '') or '').strip()
    if not base or is_loopback_base(base):
        return False
    host = urlsplit(base).hostname or ''
    if not re.fullmatch(r'\d{1,3}(\.\d{1,3}){3}', host):
        return False
    mine = urlsplit(lan_base()).hostname or ''
    return bool(mine) and not mine.startswith('127.') and mine != host


def is_loopback_base(base):
    """True when `base` points at whoever is asking — which is exactly what
    breaks OBS on a SECOND machine: 'localhost' there is the OBS box, not
    this one, so every source loads nothing."""
    host = (base or '').split('//', 1)[-1].split('/')[0]
    if host.startswith('['):                 # [::1]:8086 — IPv6 is bracketed,
        host = host[1:host.find(']')] if ']' in host else host[1:]
    else:                                    # ...so only strip a port here
        host = host.split(':')[0]
    host = host.strip().lower()
    return host in ('localhost', '127.0.0.1', '::1', '0.0.0.0', '') or \
        host.startswith('127.')


def _card_base():
    """Where OBS should fetch cards from.

    Must be ABSOLUTE — a browser source has no page to be relative to — and
    built without url_for, which needs a request context this can't rely on
    (the auto-return timer calls it from a plain thread). Auto-filled from the
    DM's own address when they open the Broadcast page; override it when OBS
    runs on a different machine from ScenePlay."""
    base = (appsettingGet('obs_card_base', '') or '').strip()
    return base.rstrip('/') if base else f'http://127.0.0.1:{DEFAULT_CARD_PORT}'


def card_url(character_id, over=False):
    """over=True asks for the opaque card — the one that covers a camera source
    still running underneath it, so the player stays audible."""
    # Flask's <int:> converter never matches a negative number, so the DM's
    # card gets its own path rather than /card/-1.
    leaf = 'dm' if character_id == DM_TILE_ID else str(character_id)
    return (f'{_card_base()}{obs_bp.url_prefix}/card/{leaf}'
            f'?t={_card_token(character_id)}' + ('&over=1' if over else ''))


@obs_bp.route('/card/dm')
def dm_card():
    """The DM's tile when they have no camera. Same token gate as a player
    card; a separate path because <int:> never matches a negative id."""
    if not token_ok(request.args.get('t', ''), _card_token(DM_TILE_ID)):
        abort(403)
    tile = dm_tile()
    return render_template('ttrpg/obs_card.html', char=tile, conditions=[],
                           is_dm=True, poll_s=card_poll_s(),
                           opaque=request.args.get('over') == '1',
                           poll_url=url_for('obs_bp.dm_card_state',
                                            t=request.args.get('t', '')),
                           theme=_theme_payload())


@obs_bp.route('/card/dm/state')
def dm_card_state():
    if not token_ok(request.args.get('t', ''), _card_token(DM_TILE_ID)):
        abort(403)
    tile = dm_tile()
    return jsonify({'name': tile.name, 'hp_current': 0, 'hp_max': 0,
                    'hp_pct': 0, 'ac': 0, 'conditions': [],
                    'player': dm_player_name(), 'is_dm': True,
                    'theme': _theme_payload()})


@obs_bp.route('/tile/dm')
def dm_tile_view():
    """The DM's camera with their name over it. Separate path for the same
    reason /card/dm is: <int:> will not match the DM's negative id."""
    token = request.args.get('t', '')
    if not token_ok(token, _card_token(DM_TILE_ID)):
        abort(403)
    tile = dm_tile()
    return render_template(
        'ttrpg/obs_tile.html', char=tile,
        player=dm_player_name(), portrait_url='',
        feed_url=tile.video_view_url(),
        strip_only=request.args.get('strip') == '1',
        conditions=[], is_dm=True, poll_s=card_poll_s(),
        poll_url=url_for('obs_bp.dm_card_state', t=token),
        theme=_theme_payload())


@obs_bp.route('/tile/<int:character_id>')
def player_tile(character_id):
    """A player's camera with their character laid over it.

    ?strip=1 drops the video and serves the character strip alone, transparent,
    to be layered over a camera source of its own. That is what the party scene
    builds, because an https feed framed inside this http page is not a secure
    context and so cannot run WebRTC at all — see obs_tile.html. Without the
    flag the feed is still framed, which works wherever the parent is https.

    Framing is only safe for the VIEW url: it is playback, needing no camera
    permission. The PUSH url must never be framed — camera delegation from a
    LAN http:// parent is blocked, which is why the player's own page links
    out to it instead."""
    token = request.args.get('t', '')
    if not token_ok(token, _card_token(character_id)):
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
        strip_only=request.args.get('strip') == '1',
        conditions=[c.condition_name for c in char.conditions] if char.conditions else [],
        poll_s=card_poll_s(),
        poll_url=url_for('obs_bp.card_state', character_id=character_id, t=token),
        theme=_theme_payload())


@obs_bp.route('/card/<int:character_id>')
def player_card(character_id):
    """Transparent stat card for OBS. No login: OBS can't hold a session, so
    the URL carries a token. compare_digest to keep it constant-time."""
    token = request.args.get('t', '')
    if not token_ok(token, _card_token(character_id)):
        abort(403)
    char = db.session.get(tblCharacters, character_id)
    if not char:
        abort(404)
    conditions = [c.condition_name for c in char.conditions] if char.conditions else []
    return render_template('ttrpg/obs_card.html', char=char,
                           conditions=conditions, is_dm=False,
                           player=player_name_for(char),
                           opaque=request.args.get('over') == '1',
                           poll_s=card_poll_s(),
                           poll_url=url_for('obs_bp.card_state',
                                            character_id=character_id,
                                            t=token),
                           theme=_theme_payload())


@obs_bp.route('/card/<int:character_id>/state')
def card_state(character_id):
    """Live values for the card — it polls this so HP/conditions track play
    without the DM touching anything."""
    if not token_ok(request.args.get('t', ''), _card_token(character_id)):
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
        'theme': _theme_payload(),
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
    if not token_ok(request.args.get('t', ''), _map_token()):
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


@obs_bp.route('/api/theme-shared', methods=['POST'])
@login_required
@dm_required
def api_theme_shared():
    """Drop the active session's own look — back to the shared default. The
    counterpart of the art slots' per-session 'clear'."""
    sid = _active_session_id()
    if sid is not None:
        for key in THEME_KEYS:
            appsettingSet(f'{key}:s{sid}', '')
        flash("This session's look cleared — back to the shared default.")
    return redirect(url_for('obs_bp.broadcast'))


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
    # Art belongs to the ACTIVE session when there is one, so each session can
    # carry its own pre/post/title/background set. With no session running the
    # upload edits the shared default that sessions fall back to.
    sid = _active_session_id()
    if sid is not None:
        setting = f'{setting}:s{sid}'
        stem = f'{stem}-s{sid}'

    if request.form.get('clear'):
        appsettingSet(setting, '')
        short = label.split(chr(8212))[0].strip()
        if sid is not None and (appsettingGet(IMAGE_SLOTS[slot][0], '')
                                or '').strip():
            flash(f'{short}: this session\'s art cleared — back to the '
                  f'shared default.')
        else:
            flash(f'{short} cleared.')
        return redirect(url_for('obs_bp.broadcast'))
    f = request.files.get('image')
    ref = (request.form.get('ref') or '').strip()
    if not (f and f.filename) and ref:
        # "Choose existing": point the slot at a shared upload or a library
        # video by reference — the stream pages resolve it like any name.
        import shared_assets
        from extensions import database
        kinds = ('image',) if slot == 'yt_thumb' else ('image', 'video')
        if not shared_assets.valid_ref(current_app.root_path, database, 'obs', ref, kinds=kinds):
            flash('That file is not available for this slot.')
            return redirect(url_for('obs_bp.broadcast'))
        appsettingSet(setting, ref)
        flash('Art set to an existing file — the stream pages pick it up within a few seconds.')
        return redirect(url_for('obs_bp.broadcast'))
    if not f or not f.filename:
        flash('No image chosen.')
        return redirect(url_for('obs_bp.broadcast'))
    ext = f.filename.rsplit('.', 1)[-1].lower()
    if ext not in TITLE_EXT | VIDEO_EXT:
        flash('Use a PNG, JPG, WEBP or GIF — or an MP4/WEBM video loop.')
        return redirect(url_for('obs_bp.broadcast'))
    os.makedirs(BG_DIR, exist_ok=True)
    raw = f.read()
    if ext in VIDEO_EXT:
        # No Pillow pass for video — it cannot read them. Size-capped instead:
        # the file is served to OBS's browser source on every reload.
        if len(raw) > VIDEO_MAX_BYTES:
            flash(f'That video is {len(raw) // (1024 * 1024)}MB — keep loops '
                  f'under {VIDEO_MAX_BYTES // (1024 * 1024)}MB.')
            return redirect(url_for('obs_bp.broadcast'))
    else:
        # Downscale before saving, like every other image intake (portraits,
        # tokens, map art all go through the same helper). These render at
        # most 1920px wide on the canvas, so a 9MB AI generation is pure
        # waste — disk, LAN bandwidth, and a decode stall in OBS's browser
        # source every reload. Animated GIFs and Pillow failures fall through
        # with the original bytes.
        from relay_broadcaster import _downscale_image
        raw, ext = _downscale_image(raw, ext, max_dim=1920)
    # A stable name per slot (per session): the browser sources cache by URL,
    # so reusing it means a re-upload replaces the art everywhere instead of
    # leaving the old file referenced.
    name = f'{stem}.{ext}'
    with open(os.path.join(BG_DIR, name), 'wb') as out:
        out.write(raw)
    for other in (TITLE_EXT | VIDEO_EXT):   # drop a previous different format
        old = os.path.join(BG_DIR, f'{stem}.{other}')
        if other != ext and os.path.exists(old):
            try:
                os.remove(old)
            except OSError:
                pass
    appsettingSet(setting, name)
    flash('Art updated — the stream pages pick it up within a few seconds.')
    return redirect(url_for('obs_bp.broadcast'))


PANEL_MODES = ('bg', 'title', 'info', 'dice', 'pre', 'intermission', 'post')


@obs_bp.route('/panel')
def panel_view():
    """One page, three modes — see the template header."""
    if not token_ok(request.args.get('t', ''), _panel_token()):
        abort(403)
    mode = (request.args.get('mode') or 'info').strip().lower()
    return render_template('ttrpg/obs_panel.html',
                           mode=mode if mode in PANEL_MODES else 'info',
                           # Same table that defines the show scenes, so a new
                           # card can never be a scene the page won't paint.
                           card_modes=sorted(SHOW_SOURCE),
                           state_url=url_for('obs_bp.panel_state',
                                             t=_panel_token()),
                           poll_s=panel_poll_s(),
                           theme=_theme_payload())


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
    if not token_ok(request.args.get('t', ''), _panel_token()):
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
    # The session's name rides the strip as a subtitle — "which episode is
    # this" for the audience. The page drops it when it would just repeat the
    # main title (no campaign set, so the session IS the title).
    session_name = (sess.title if sess else '') or ''
    bg = art_setting('obs_party_bg')

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
        'bg_url': _art_url(bg),
        'title': title,
        'session': session_name,
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
        'theme': _theme_payload(),
        # Pop-over mode: the panel slides in because of a roll OR a fresh
        # note — it shows whichever happened last. With the panel permanently
        # on screen, notes keep their old priority.
        'dice_popover': dice_autohide_on(),
        'show_notes': (_dice_state['note_stamp'] >= _dice_state['roll_stamp']
                       and bool(_info_lines())),
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
        textures_url=url_for('obs_bp.map_textures', t=_map_token()),
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
        # Where the DM last clicked, for the 3D camera to turn towards.
        'look_at': look_at_point(),
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


@obs_bp.route('/map/textures')
def map_textures():
    """Texture-library manifest for the 3D branch — the browser source is
    token-authed, so it can't hit the login-gated /ttrpg/textures/manifest.
    Texture image files themselves are plain /static URLs."""
    _check_map_token()
    from routes.textures import texture_manifest
    return jsonify({'ok': True, 'textures': texture_manifest()})


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
    # A look direction belongs to the character it was aimed from. Dropping it
    # with the pin stops a stale heading being applied to whoever is featured
    # next, minutes later.
    appsettingSet('obs_look_at', '')


def look_at_point():
    """{'col','row','seq'} the DM last clicked on the map, or None.

    seq is what the map source watches: the same cell clicked twice must
    still re-aim, so identity can't be the coordinates alone."""
    raw = (appsettingGet('obs_look_at', '') or '').strip()
    if not raw:
        return None
    try:
        col, row, seq = raw.split(',')
        return {'col': int(col), 'row': int(row), 'seq': int(seq)}
    except (TypeError, ValueError):
        return None


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
    img = art_setting('obs_title_image')
    campaign = ''
    if sess and sess.campaign_id:
        from models.campaigns import tblcampaigns
        camp = db.session.get(tblcampaigns, sess.campaign_id)
        campaign = camp.campaign_name if camp else ''
    return {
        'image_url': (_url_for('static', filename=f'uploads/obs/{img}',
                               v=_art_mtime(img))
                      if img else ''),
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
