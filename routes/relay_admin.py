import requests
import secrets
import logging
from flask import (Blueprint, render_template, redirect, url_for,
                   request, flash, jsonify, current_app)
from flask_login import login_required
from routes.auth import dm_required
from sql import appsettingGet, appsettingSet

log = logging.getLogger(__name__)

relay_admin_bp = Blueprint('relay_admin_bp', __name__, url_prefix='/ttrpg/relay')


# ── helpers ───────────────────────────────────────────────────────────────────

def _relay_cfg():
    return {
        'enabled':          appsettingGet('relay_enabled',         '0'),
        'url':              appsettingGet('relay_url',             ''),
        'secret':           appsettingGet('relay_secret',          ''),
        'session_id':       appsettingGet('relay_session_id',      ''),
        'code':             appsettingGet('relay_session_code',    ''),
        'last_sync':        appsettingGet('relay_last_sync',       '—'),
        'roll_cleared_at':  appsettingGet('relay_roll_cleared_at', ''),
        'audio_enabled':    appsettingGet('relay_audio_enabled',   '1'),
    }


# ── routes ────────────────────────────────────────────────────────────────────

@relay_admin_bp.route('/')
@login_required
@dm_required
def status():
    import json as _json
    cfg = _relay_cfg()
    logged_in = []

    # Age of the last successful receiver poll, so a stalled sync is visible
    # at the table instead of being discovered mid-combat. last_sync is stored
    # by relay_receiver as UTC '%Y-%m-%d %H:%M:%S'.
    sync_age = None
    try:
        from datetime import datetime, timezone
        ts = datetime.strptime(cfg['last_sync'], '%Y-%m-%d %H:%M:%S')
        sync_age = int((datetime.now(timezone.utc).replace(tzinfo=None) - ts).total_seconds())
    except (ValueError, TypeError):
        pass

    if cfg['session_id'] and cfg['url'] and cfg['enabled'] == '1':
        try:
            resp = requests.get(
                cfg['url'].rstrip('/') + f"/api/v1/session/{cfg['session_id']}/sync",
                headers={'X-Relay-Secret': cfg['secret']},
                timeout=5,
            )
            if resp.ok:
                for rc in resp.json().get('characters', []):
                    if not rc.get('has_joined'):
                        continue
                    sheet = {}
                    try:
                        sheet = _json.loads(rc.get('sheet_json') or '{}')
                    except Exception:
                        pass
                    hp_current = rc.get('hp_current') or 0
                    hp_max     = rc.get('hp_max') or 1
                    logged_in.append({
                        'player_name':  rc.get('player_name', ''),
                        'username':     rc.get('username', ''),
                        'display_name': rc.get('display_name', ''),
                        'char_class':   sheet.get('class', '—'),
                        'level':        sheet.get('level', '—'),
                        'hp_current':   hp_current,
                        'hp_max':       hp_max,
                        'hp_pct':       round(100 * hp_current / max(1, hp_max)),
                        'joined_at':    (rc.get('joined_at') or '')[:16].replace('T', ' '),
                    })
        except Exception as e:
            log.debug('status logged-in fetch error: %s', e)

        # Live presence: the relay marks players present on SSE connect +
        # 30s heartbeats and absent on disconnect, so this distinguishes
        # "has an account and joined at some point" from "connected right
        # now". Missing from the dict or stale-hearted (>90s) = offline.
        presence = {}
        try:
            presp = requests.get(
                cfg['url'].rstrip('/') + f"/api/v1/session/{cfg['session_id']}/presence",
                headers={'X-Relay-Secret': cfg['secret']},
                timeout=5,
            )
            if presp.ok:
                presence = presp.json().get('presence', {}) or {}
        except Exception as e:
            log.debug('status presence fetch error: %s', e)
        for p in logged_in:
            # Presence keys vary by relay version: character name on newer
            # code, username on the currently deployed one — accept either.
            age = presence.get(p['player_name'])
            if age is None:
                age = presence.get(p['username'])
            p['online'] = age is not None and age < 90

    return render_template('ttrpg/relay_status.html', cfg=cfg, logged_in=logged_in,
                           sync_age=sync_age)


@relay_admin_bp.route('/api/health')
@login_required
@dm_required
def api_health():
    """Lightweight relay-health check for the DM banner on every TTRPG page.

    Signals: relay_last_sync (receiver heartbeat — written after each
    successful poll, so staleness means the portal<->local sync is broken)
    and relay_push_last_drop (a push the queue gave up on — silent data loss
    toward the portal). Only alarms when the relay is enabled AND a session
    exists; an idle relay is not an error."""
    from datetime import datetime, timezone
    cfg = _relay_cfg()
    if cfg['enabled'] != '1' or not cfg['url'] or not cfg['session_id']:
        return jsonify({'enabled': False, 'ok': True, 'problems': []})

    problems = []

    # receiver heartbeat
    sync_age = None
    try:
        ts = datetime.strptime(cfg['last_sync'], '%Y-%m-%d %H:%M:%S')
        sync_age = int((datetime.now(timezone.utc).replace(tzinfo=None) - ts).total_seconds())
    except (ValueError, TypeError):
        pass
    if sync_age is None:
        problems.append('Relay sync has not completed yet — players are not syncing.')
    elif sync_age > 90:
        mins = sync_age // 60
        problems.append(f'Relay sync stalled — last contact '
                        f'{f"{mins}m" if mins else f"{sync_age}s"} ago. '
                        f'Player moves and sheet changes are NOT reaching this server.')

    # dropped pushes (local -> relay data loss)
    drop = appsettingGet('relay_push_last_drop', '') or ''
    if drop:
        try:
            ts_s, key, err = drop.split('|', 2)
            age = (datetime.now(timezone.utc).replace(tzinfo=None)
                   - datetime.strptime(ts_s, '%Y-%m-%d %H:%M:%S')).total_seconds()
            if age < 600:   # only recent drops — old noise self-clears
                if '/session/' in err and cfg['session_id'] not in err:
                    # drop targeted a session that is no longer ours — stale
                    pass
                elif '404' in err:
                    # the relay doesn't know our session (redeployed, or a New
                    # Session was made from another ScenePlay box) — re-pushing
                    # can't help; a fresh session can.
                    problems.append('The relay no longer knows this session '
                                    '(it may have restarted, or New Session was used '
                                    'on another server). Create a New Session and have '
                                    'players log in again.')
                else:
                    problems.append(f'A push to the relay was dropped {int(age // 60)}m ago '
                                    f'({key}: {err}). Remote players may be out of date — '
                                    f'use Sync Characters to re-push.')
        except ValueError:
            pass

    return jsonify({'enabled': True, 'ok': not problems, 'problems': problems,
                    'sync_age': sync_age})


@relay_admin_bp.route('/api/presence')
@login_required
@dm_required
def api_presence():
    """Live online/offline per portal player, polled by the status page so
    the Players Online table updates without a refresh."""
    cfg = _relay_cfg()
    if cfg['enabled'] != '1' or not cfg['url'] or not cfg['session_id']:
        return jsonify({'enabled': False, 'online': {}})
    presence = {}
    try:
        resp = requests.get(
            cfg['url'].rstrip('/') + f"/api/v1/session/{cfg['session_id']}/presence",
            headers={'X-Relay-Secret': cfg['secret']},
            timeout=5,
        )
        if resp.ok:
            presence = resp.json().get('presence', {}) or {}
    except Exception as e:
        log.debug('api_presence fetch error: %s', e)
    # Same liveness rule as the page render: heartbeat younger than 90s
    online = {name: (age is not None and age < 90)
              for name, age in presence.items()}
    return jsonify({'enabled': True, 'online': online})


@relay_admin_bp.route('/toggle', methods=['POST'])
@login_required
@dm_required
def toggle():
    current = appsettingGet('relay_enabled', '0')
    new_val = '0' if current == '1' else '1'
    appsettingSet('relay_enabled', new_val)

    if new_val == '1':
        _start_receiver()
        import relay_broadcaster
        relay_broadcaster.push_all_characters()
        relay_broadcaster.push_session_users()
        relay_broadcaster.push_library()   # same set as generate-code / Party Sync
        flash('Relay enabled — receiver started and party synced.')
    else:
        _stop_receiver()
        flash('Relay disabled.')

    return redirect(url_for('relay_admin_bp.status'))


@relay_admin_bp.route('/save-config', methods=['POST'])
@login_required
@dm_required
def save_config():
    relay_url    = request.form.get('relay_url', '').strip()
    relay_secret = request.form.get('relay_secret', '').strip()
    if relay_url:
        appsettingSet('relay_url',    relay_url)
    if relay_secret:
        appsettingSet('relay_secret', relay_secret)
    # Checkbox: absent from the form data when unchecked. Applies at the
    # next track start / push rotation (relay_audio_stream re-reads config).
    appsettingSet('relay_audio_enabled',
                  '1' if request.form.get('relay_audio_enabled') else '0')
    flash('Relay configuration saved.')
    return redirect(url_for('relay_admin_bp.status'))


@relay_admin_bp.route('/generate-code', methods=['POST'])
@login_required
@dm_required
def generate_code():
    cfg = _relay_cfg()
    if not cfg['url'] or not cfg['secret']:
        flash('Set relay URL and secret before generating a code.')
        return redirect(url_for('relay_admin_bp.status'))

    try:
        resp = requests.post(
            cfg['url'].rstrip('/') + '/api/v1/session/create',
            headers={'X-Relay-Secret': cfg['secret'], 'Content-Type': 'application/json'},
            json={},
            timeout=8,
        )
        resp.raise_for_status()
        data = resp.json()
        code       = data.get('code', '')
        session_id = data.get('session_id', '')
        if not code or not session_id:
            flash('Relay returned an unexpected response — check relay logs.')
            return redirect(url_for('relay_admin_bp.status'))

        appsettingSet('relay_session_code', code)
        appsettingSet('relay_session_id',   session_id)

        # New relay session = all relay token rows purged and seq counters
        # restarted; drop the local relay-seq mirror so no stale value can
        # collide with (and swallow) a fresh move.
        from extensions import db
        from models.tblTokenPositions import tblTokenPositions
        tblTokenPositions.query.delete(synchronize_session=False)
        db.session.commit()

        # Push drops recorded against the PREVIOUS session are moot now —
        # clear them so the health banner doesn't nag about a dead session.
        appsettingSet('relay_push_last_drop', '')

        # Push all current party characters and D&D library into the fresh session immediately
        import relay_broadcaster
        relay_broadcaster.push_all_characters()
        relay_broadcaster.push_session_users()
        relay_broadcaster.push_library()

        flash(f'New session created — join code: {code}. Party pushed to relay.')
    except Exception as e:
        log.warning('generate_code relay error: %s', e)
        flash(f'Could not reach relay: {e}')

    return redirect(url_for('relay_admin_bp.status'))


@relay_admin_bp.route('/sync-characters', methods=['POST'])
@login_required
@dm_required
def sync_characters():
    import relay_broadcaster
    relay_broadcaster.push_all_characters()
    relay_broadcaster.push_session_users()
    relay_broadcaster.push_library()
    flash('Party characters, user accounts and library pushed to relay.')
    return redirect(url_for('relay_admin_bp.status'))


@relay_admin_bp.route('/party')
@login_required
@dm_required
def party():
    import json as _json
    cfg = _relay_cfg()
    relay_chars = []
    error = None

    if cfg['session_id'] and cfg['url']:
        try:
            resp = requests.get(
                cfg['url'].rstrip('/') + f"/api/v1/session/{cfg['session_id']}/sync",
                headers={'X-Relay-Secret': cfg['secret']},
                timeout=8,
            )
            resp.raise_for_status()
            raw_chars = resp.json().get('characters', [])
            for rc in raw_chars:
                # Only show players who have actually logged in on the relay site
                if not rc.get('has_joined', False):
                    continue
                sheet = {}
                try:
                    sheet = _json.loads(rc.get('sheet_json') or '{}')
                except Exception:
                    pass
                hp_current = rc.get('hp_current', 0) or 0
                hp_max     = rc.get('hp_max', 1) or 1
                relay_chars.append({
                    'player_name': rc.get('player_name', ''),
                    'sheet':       sheet,
                    'hp_current':  hp_current,
                    'hp_max':      hp_max,
                    'hp_pct':      round(100 * hp_current / max(1, hp_max)),
                    'updated_at':  (rc.get('updated_at') or '')[:16].replace('T', ' '),
                    'joined_at':   (rc.get('joined_at') or '')[:16].replace('T', ' '),
                    'char_id':     rc.get('id', ''),
                })
        except Exception as e:
            log.warning('party relay fetch error: %s', e)
            error = str(e)

    return render_template('ttrpg/relay_party.html',
                           party=relay_chars,
                           cfg=cfg,
                           error=error)


@relay_admin_bp.route('/clear-rolls', methods=['POST'])
@login_required
@dm_required
def clear_rolls():
    from datetime import datetime, timezone
    from extensions import db
    from models.tblRollLog import tblRollLog
    from models.ttrpg import tblDiceRolls
    watermark = datetime.now(timezone.utc).isoformat()
    appsettingSet('relay_roll_cleared_at', watermark)
    tblDiceRolls.query.delete()
    tblRollLog.query.delete()
    db.session.commit()
    flash('Local roll history cleared. The receiver will ignore relay rolls made before this point.', 'success')
    return redirect(url_for('relay_admin_bp.status'))


@relay_admin_bp.route('/rolls')
@login_required
@dm_required
def rolls():
    from models.tblRollLog import tblRollLog

    session_id = appsettingGet('relay_session_id', '')
    entries = []

    if session_id:
        try:
            sid = int(session_id)
        except (ValueError, TypeError):
            sid = None

        if sid:
            entries = (tblRollLog.query
                       .filter_by(session_id=sid)
                       .order_by(tblRollLog.id.desc())
                       .limit(200)
                       .all())

    return render_template('ttrpg/relay_rolls.html', entries=entries,
                           session_id=session_id)


# ── Server-to-server API (called by relay, no browser session required) ──────

def _require_relay_secret():
    """Return None if the request carries the correct relay secret, else an error response."""
    stored = appsettingGet('relay_secret', '')
    incoming = request.headers.get('X-Relay-Secret', '')
    if not stored or incoming != stored:
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    return None


@relay_admin_bp.route('/api/auth/verify', methods=['POST'])
def api_auth_verify():
    """Relay calls this to verify a player's ScenePlay credentials.

    Request  (JSON):  { "username": str, "password": str }
    Auth:             X-Relay-Secret header

    Response 200:     { ok, user_id, username, display_name,
                        relay_session_id, character: { name, class, level,
                        hp_current, hp_max, ac, speed } | null }
    Response 401:     { ok: false, error }
    """
    err = _require_relay_secret()
    if err:
        return err

    data     = request.get_json(silent=True) or {}
    username = data.get('username', '').strip()
    password = data.get('password', '')

    if not username or not password:
        return jsonify({'ok': False, 'error': 'missing credentials'}), 400

    from models.user import tblUsers
    from models.ttrpg import tblSessions

    user = tblUsers.query.filter_by(username=username, active=1).first()
    if not user or not user.check_password(password):
        return jsonify({'ok': False, 'error': 'invalid credentials'}), 401

    # Find the character this user has in the active session
    active_sess = tblSessions.query.filter_by(status='active').first()
    character   = None
    if active_sess:
        for sp in active_sess.party:
            char = sp.character
            if char and char.user_id == user.user_id:
                portrait_url = ''
                if char.portrait_path:
                    portrait_url = url_for('static',
                                           filename=f'uploads/portraits/{char.portrait_path}',
                                           _external=True)
                character = {
                    'name':         char.name,
                    'class':        char.char_class,
                    'race':         char.race,
                    'level':        char.level,
                    'hp_current':   char.hp_current,
                    'hp_max':       char.hp_max,
                    'ac':           char.ac,
                    'speed':        char.speed,
                    'portrait_url': portrait_url,
                }
                break

    return jsonify({
        'ok':               True,
        'user_id':          user.user_id,
        'username':         user.username,
        'display_name':     user.display_name,
        'relay_session_id': appsettingGet('relay_session_id', ''),
        'character':        character,
    })


@relay_admin_bp.route('/api/session/info', methods=['GET'])
def api_session_info():
    """Relay calls this to get current session and map state.

    Auth: X-Relay-Secret header

    Response 200: { relay_session_id, code, sceneplay_session_id,
                    map: { url, grid_cols, grid_rows, tokens } | null }
    """
    err = _require_relay_secret()
    if err:
        return err

    from models.ttrpg import tblSessions, tblBattleMaps
    from flask import url_for
    from extensions import db
    import json as _json
    import traceback as _tb

    cfg = _relay_cfg()

    try:
        active_sess = tblSessions.query.filter_by(status='active').first()
        map_data    = None

        if active_sess:
            bm = tblBattleMaps.query.filter_by(
                session_id=active_sess.session_id, is_active=1).first()
            if bm:
                bg_url = (url_for('static',
                                   filename=f'uploads/battlemaps/{bm.bg_image}',
                                   _external=True)
                          if bm.bg_image else '')
                tokens = []
                for t in bm.tokens:
                    tok = {
                        'token_id':    t.token_id,
                        'token_type':  t.entity_type,
                        'label':       '',
                        'x_pct':       t.col / max(1, bm.grid_cols - 1),
                        'y_pct':       t.row / max(1, bm.grid_rows - 1),
                        'character_id': None,
                    }
                    if t.entity_type == 'player':
                        from models.ttrpg import tblCharacters
                        char = db.session.get(tblCharacters, t.entity_id)
                        if char:
                            tok['label']        = char.name
                            tok['character_id'] = t.entity_id
                            tok['hp_current']   = char.hp_current
                            tok['hp_max']       = char.hp_max
                    elif t.entity_type == 'monster':
                        from models.ttrpg import tblSessionMonsters
                        sm = db.session.get(tblSessionMonsters, t.entity_id)
                        if sm:
                            tok['label']      = sm.display_name
                            tok['hp_current'] = sm.hp_current
                            tok['hp_max']     = sm.hp_max
                    tokens.append(tok)
                map_data = {
                    'url':       bg_url,
                    'grid_cols': bm.grid_cols,
                    'grid_rows': bm.grid_rows,
                    'tokens':    tokens,
                }
    except Exception as exc:
        log.error('api_session_info error: %s\n%s', exc, _tb.format_exc())
        return jsonify({'error': str(exc), 'trace': _tb.format_exc()}), 500

    return jsonify({
        'relay_session_id':    cfg['session_id'],
        'code':                cfg['code'],
        'sceneplay_session_id': active_sess.session_id if active_sess else None,
        'map':                 map_data,
    })


# ── receiver thread helpers ───────────────────────────────────────────────────

def _start_receiver():
    try:
        import relay_receiver
        relay_receiver.start(current_app._get_current_object())
    except Exception as e:
        log.warning('Could not start relay receiver: %s', e)


def _stop_receiver():
    try:
        import relay_receiver
        relay_receiver.stop()
    except Exception as e:
        log.warning('Could not stop relay receiver: %s', e)
