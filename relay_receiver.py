import logging
import threading

log = logging.getLogger(__name__)

_thread = None
_stop   = threading.Event()


def start(app):
    global _thread, _stop
    _stop.clear()
    _thread = threading.Thread(
        target=_run, args=(app,), daemon=True, name='relay-receiver'
    )
    _thread.start()
    log.info('Relay receiver started')


def stop():
    _stop.set()
    log.info('Relay receiver stop requested')


def _run(app):
    with app.app_context():
        while not _stop.is_set():
            try:
                _poll()
            except Exception as e:
                log.warning('Relay receiver poll error: %s', e)
            _stop.wait(2)


def _poll():
    from sql import appsettingGet, appsettingSet
    enabled    = appsettingGet('relay_enabled', '0')
    relay_url  = appsettingGet('relay_url', '')
    secret     = appsettingGet('relay_secret', '')
    session_id = appsettingGet('relay_session_id', '')

    if enabled != '1' or not relay_url or not session_id:
        return

    import requests
    from datetime import datetime, timezone
    from extensions import db
    import json as _json
    from models.tblTokenPositions import tblTokenPositions
    from models.tblRollLog import tblRollLog
    from models.ttrpg import tblCharacters, tblSessions, tblBattleMaps, tblBattleMapTokens, tblDiceRolls

    url  = relay_url.rstrip('/') + f'/api/v1/session/{session_id}/sync'
    resp = requests.get(url, headers={'X-Relay-Secret': secret}, timeout=8)
    if resp.status_code != 200:
        log.warning('Relay sync returned %s', resp.status_code)
        return

    payload  = resp.json()
    now      = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
    bm_tok_ts = datetime.now(timezone.utc).isoformat()   # ISO UTC, comparable with relay timestamps

    # Resolve the local integer session_id and active battlemap for FK columns
    active_sess = tblSessions.query.filter_by(status='active').first()
    local_sid   = active_sess.session_id if active_sess else None
    active_bm   = (tblBattleMaps.query
                   .filter_by(session_id=local_sid, is_active=1)
                   .first()) if local_sid else None

    # --- token positions (relay tokens array) ---
    # Relay token shape: { id, session_id, character_id, label, x_pct, y_pct, token_type, updated_at }
    for tok in payload.get('tokens', []):
        label      = tok.get('label', '')
        x_pct      = tok.get('x_pct')
        y_pct      = tok.get('y_pct')
        token_type = tok.get('token_type', 'player')
        if not label or local_sid is None or x_pct is None or y_pct is None:
            continue

        # Update tblTokenPositions (relay mirror)
        tp = tblTokenPositions.query.filter_by(session_id=local_sid, label=label).first()
        if tp:
            tp.x_pct      = x_pct
            tp.y_pct      = y_pct
            tp.updated_at = now
        else:
            db.session.add(tblTokenPositions(
                session_id  = local_sid,
                label       = label,
                x_pct       = x_pct,
                y_pct       = y_pct,
                token_type  = token_type,
                updated_at  = now,
            ))

        # Update tblBattleMapTokens so the local battlemap poll sees relay moves.
        # Both the relay's updated_at and bm_tok.updated_at use ISO UTC after the
        # map_activate / token_add / token_move changes, so we can compare them
        # directly: only apply the relay position if it is strictly newer than the
        # local battlemap record (meaning the player genuinely moved after the map
        # was last set up / activated).
        if active_bm and token_type == 'player':
            char = tblCharacters.query.filter_by(name=label, active=1).first()
            if char:
                bm_tok = tblBattleMapTokens.query.filter_by(
                    map_id=active_bm.map_id, entity_type='player', entity_id=char.character_id
                ).first()
                if bm_tok:
                    tok_ts = tok.get('updated_at', '')
                    bm_ts  = bm_tok.updated_at or ''
                    # Skip if local record is present and relay position is not newer
                    if bm_ts and tok_ts and tok_ts <= bm_ts:
                        continue
                    bm_tok.col        = max(0, min(active_bm.grid_cols - 1,
                                                   round(x_pct * (active_bm.grid_cols - 1))))
                    bm_tok.row        = max(0, min(active_bm.grid_rows - 1,
                                                   round(y_pct * (active_bm.grid_rows - 1))))
                    bm_tok.updated_at = bm_tok_ts

    # --- roll log (relay roll_log array) ---
    # Relay roll shape: { id, session_id, player_name, roll_expr, result, breakdown, rolled_at }
    roll_cleared_at = appsettingGet('relay_roll_cleared_at', '')
    for roll in payload.get('roll_log', []):
        rolled_at = roll.get('rolled_at', '')
        if not rolled_at or local_sid is None:
            continue
        if roll_cleared_at and rolled_at <= roll_cleared_at:
            continue
        existing = tblRollLog.query.filter_by(
            session_id  = local_sid,
            player_name = roll.get('player_name', ''),
            rolled_at   = rolled_at,
        ).first()
        if not existing:
            db.session.add(tblRollLog(
                session_id  = local_sid,
                player_name = roll.get('player_name', ''),
                roll_expr   = roll.get('roll_expr', ''),
                result      = roll.get('result', 0),
                breakdown   = roll.get('breakdown', ''),
                rolled_at   = rolled_at,
            ))
            # prune oldest beyond 500
            if tblRollLog.query.filter_by(session_id=local_sid).count() > 500:
                oldest = (tblRollLog.query
                          .filter_by(session_id=local_sid)
                          .order_by(tblRollLog.id)
                          .first())
                if oldest:
                    db.session.delete(oldest)

        # Also write to tblDiceRolls so relay rolls appear in the 50-roll history.
        # Local rolls use "YYYY-MM-DD HH:MM:SS"; relay timestamps are ISO with T and TZ.
        # Normalize to local format so the dedup check matches local-broadcast-echo rolls.
        player_name = roll.get('player_name', '')
        relay_expr  = roll.get('roll_expr', '')
        relay_total = roll.get('result', 0)
        ts_norm = (rolled_at[:10] + ' ' + rolled_at[11:19]
                   if rolled_at and 'T' in rolled_at else (rolled_at or '')[:19])
        # Primary dedup: normalized timestamp + char_name
        existing_dr = tblDiceRolls.query.filter_by(
            char_name = player_name,
            rolled_at = ts_norm,
        ).first()
        # Fallback dedup: same char, same result, same base expression (catches ±1s clock skew)
        if not existing_dr:
            expr_base = relay_expr.split()[0] if relay_expr else ''
            existing_dr = (tblDiceRolls.query
                .filter_by(char_name=player_name, total=relay_total)
                .filter(tblDiceRolls.expression == expr_base)
                .first())
        if not existing_dr:
            breakdown_str = roll.get('breakdown', '')
            try:
                dice_list = [int(x.strip()) for x in breakdown_str.split(',') if x.strip()]
            except (ValueError, AttributeError):
                dice_list = []
            db.session.add(tblDiceRolls(
                char_name  = player_name,
                expression = expr_base or relay_expr,
                label      = '',
                dice_json  = _json.dumps(dice_list),
                modifier   = 0,
                total      = relay_total,
                adv_mode   = 'normal',
                rolled_at  = ts_norm,
            ))
            db.session.flush()
            old = db.session.query(tblDiceRolls.roll_id).order_by(
                tblDiceRolls.roll_id.desc()).offset(50).all()
            if old:
                tblDiceRolls.query.filter(
                    tblDiceRolls.roll_id.in_([r[0] for r in old])
                ).delete(synchronize_session=False)

    # --- character HP from relay characters array ---
    # Relay character shape: { id, player_name, sheet_json, hp_current, hp_max, updated_at }
    # Match to local characters by name (best-effort)
    for rc in payload.get('characters', []):
        player_name = rc.get('player_name', '')
        hp_current  = rc.get('hp_current')
        hp_max      = rc.get('hp_max')
        if not player_name or hp_current is None:
            continue
        char = tblCharacters.query.filter_by(name=player_name, active=1).first()
        if char:
            char.hp_current = hp_current
            if hp_max is not None:
                char.hp_max = hp_max

    db.session.commit()
    appsettingSet('relay_last_sync', now)
