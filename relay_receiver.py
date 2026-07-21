import logging
import threading

log = logging.getLogger(__name__)

_thread = None
_stop   = threading.Event()


def _relay_ts_to_local(rolled_at):
    """Relay roll timestamps are ISO UTC; convert to LOCAL wall-clock
    'YYYY-MM-DD HH:MM:SS' so relay rolls sort chronologically against local
    rolls (which use local time). Falls back to a plain strip on any parse error."""
    from datetime import datetime, timezone
    s = (rolled_at or '').strip()
    if not s:
        return ''
    try:
        if s.endswith('Z'):
            s = s[:-1] + '+00:00'
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone().strftime('%Y-%m-%d %H:%M:%S')
    except Exception:
        if 'T' in s:
            return s[:10] + ' ' + s[11:19]
        return s[:19]


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
        failures = 0
        while not _stop.is_set():
            try:
                _poll()
                failures = 0
            except Exception as e:
                failures += 1
                log.warning('Relay receiver poll error (streak %d): %s', failures, e)
                # Recover the session so a transient flush error doesn't wedge
                # every subsequent poll ("transaction has been rolled back").
                try:
                    from extensions import db
                    db.session.rollback()
                except Exception:
                    pass
            # 2s normally; back off toward 30s while the relay is unreachable so
            # a sleeping/offline relay isn't hammered at full speed.
            delay = 2 if failures == 0 else min(30, 2 ** (failures + 1))
            _stop.wait(delay)


def _relay_map_matches(relay_ids, local_ids):
    """True when the relay's pushed map describes the LOCAL active map.

    Subset — not equality: the map push legitimately omits tokens whose entity
    is gone (deleted monster, deactivated character), and a freshly added
    token lags the in-flight push, so the relay often knows FEWER tokens than
    the local map. A different map's rows can never pass: battlemap token ids
    are unique per map, so any old-map id fails the subset test."""
    return relay_ids <= local_ids


# ── Map auto-repush ──────────────────────────────────────────────────────────
# The relay's stored map can silently go stale: a push dropped after retries,
# or a relay restart wiping its ephemeral disk. Players who log in then get an
# old/blank map until the DM happens to edit something. The receiver already
# sees the relay's map_json every poll, so when it stays out of sync with the
# local live map for several consecutive polls (a single mismatch usually just
# means a push is still in flight/debounced), re-push it — bypassing the
# broadcaster's content-hash dedup. The cooldown doubles while the mismatch
# persists so an unfixable relay (e.g. disk full) isn't re-sent a video-sized
# payload every minute.
_MAP_RESYNC_POLLS    = 3
_MAP_RESYNC_COOLDOWN = 60.0
_map_resync = {'streak': 0, 'last': 0.0, 'cooldown': _MAP_RESYNC_COOLDOWN}


def _map_out_of_sync(raw_map, local_ids, bg_expected):
    """Pure decision: does the relay's stored map_json describe the local live
    map? Out of sync when it's missing/unparseable, carries alien token ids,
    or serves a different background file. `bg_expected` is the relay-side
    filename the local background resolves to ('<sha32>.<ext>'), or None to
    skip the background check. Token ids use the same subset rule as
    _relay_map_matches; background URLs that aren't relay-hosted files
    (co-located http, data:) can't be compared and are trusted."""
    import json
    if not raw_map:
        return True
    try:
        mp = json.loads(raw_map)
        relay_ids = {int(t['token_id']) for t in (mp.get('tokens') or [])
                     if t.get('token_id') is not None}
    except (ValueError, TypeError, KeyError, AttributeError):
        return True
    if not relay_ids <= local_ids:
        return True
    if bg_expected:
        url = mp.get('url') or ''
        if url.startswith('/battlemaps/'):
            return url.rsplit('/', 1)[-1] != bg_expected
        if not url:
            return True
    return False


def _maybe_repush_map(active_bm, raw_map):
    """Track out-of-sync streak for the live map and re-push when it persists."""
    import time as _time
    bg_expected = None
    try:
        import relay_broadcaster
        if active_bm.bg_image:
            _data, _ext, _sha = relay_broadcaster._battlemap_data(active_bm.bg_image)
            if _sha:
                bg_expected = f'{_sha}.{_ext}'
    except Exception:
        pass

    if not _map_out_of_sync(raw_map, {t.token_id for t in active_bm.tokens},
                            bg_expected):
        _map_resync['streak'] = 0
        _map_resync['cooldown'] = _MAP_RESYNC_COOLDOWN
        return

    _map_resync['streak'] += 1
    if _map_resync['streak'] < _MAP_RESYNC_POLLS:
        return
    now = _time.monotonic()
    if now - _map_resync['last'] < _map_resync['cooldown']:
        return
    _map_resync['last'] = now
    _map_resync['cooldown'] = min(_map_resync['cooldown'] * 2, 900.0)
    _do_repush(active_bm)


def _do_repush(active_bm):
    try:
        import relay_broadcaster
        from flask import current_app
        from routes.battlemap import _push_map_state
        relay_broadcaster.reset_map_push_cache()
        # test_request_context: _push_map_state builds url_for(..., _external)
        # links, which need a request context this background thread lacks. The
        # localhost URLs it yields are only the last-resort fallback — the push
        # carries the background via the sha/image_data handshake.
        with current_app.test_request_context():
            _push_map_state(active_bm)
        log.info('Auto-repushed battle map %s — relay map state was stale or missing',
                 active_bm.map_id)
    except Exception as exc:
        log.warning('Battle map auto-repush failed: %s', exc)


def _should_apply_relay_pos(tok_seq, last_seq, tok_ts, bm_ts):
    """Decide whether a relay token position should overwrite the local one.

    Preferred path: relay-assigned per-token write sequences (`seq`), which are
    immune to clock skew between this machine and the relay host. A seq LOWER
    than the last one we processed means the relay's counter restarted (its
    token rows are cleared on map change / New Session) — that write is new,
    not stale. Falls back to the legacy cross-machine ISO-timestamp compare
    only when the relay predates the seq column (mid-upgrade compatibility)."""
    if tok_seq is not None:
        return tok_seq != (last_seq or 0)
    return not (bm_ts and tok_ts and tok_ts <= bm_ts)


# Ring of the most recent relay mutation IDs this instance has applied.
# Persisted in tblAppSettings so it survives restarts. 500 comfortably exceeds
# what a table of players could stage between two 2-second polls.
_LEDGER_KEY  = 'relay_applied_mutation_ids'
_LEDGER_SIZE = 500


def _applied_ledger_load():
    """Return the set of recently applied relay mutation IDs."""
    import json as _json
    from sql import appsettingGet
    try:
        ids = _json.loads(appsettingGet(_LEDGER_KEY, '[]') or '[]')
        return set(int(i) for i in ids)
    except (ValueError, TypeError):
        return set()


def _applied_ledger_save(ledger, newly_applied):
    """Add newly applied IDs to the ledger and persist the newest _LEDGER_SIZE."""
    import json as _json
    from sql import appsettingSet
    ledger.update(newly_applied)
    ring = sorted(ledger)[-_LEDGER_SIZE:]
    try:
        appsettingSet(_LEDGER_KEY, _json.dumps(ring))
    except Exception as exc:
        log.warning('Applied-mutation ledger save failed: %s', exc)


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

    # Token and roll syncing must NEVER starve mutation processing below —
    # a deterministic error here would otherwise kill HP/sheet mutations on
    # every poll. Failures roll back and retry next poll.
    try:
        # --- token positions (relay tokens array) ---
        # Relay token shape: { id, session_id, character_id, label, x_pct, y_pct,
        #                      token_type, updated_at, seq }
        # `seq` comes from the relay's SESSION-monotonic write counter; we track
        # the last seq we processed in tblTokenPositions.relay_seq and apply only
        # unseen writes — no cross-machine clock comparison involved.
        #
        # (The old 'baseline fast-forward' flag is gone: the relay clears its
        # token rows when a new map lands, so there are no stale rows to fast-
        # forward past — and the flag was eating moves made right after a map
        # load. Stale-row protection is the map-identity guard below.)

        # Map-identity guard: relay token rows are matched to local tokens BY
        # CHARACTER LABEL, so while the relay is still showing the PREVIOUS map
        # (the map push is debounced/queued and can lag activation), its rows
        # describe old-map positions and must not move tokens on the new map.
        # The relay's current map_json carries the pushed token_ids — only apply
        # relay moves when they match the local active map's token ids.
        relay_map_ok = True
        if active_bm is not None:
            raw_map = (payload.get('session') or {}).get('map_json')
            if raw_map:
                try:
                    import json as _json
                    relay_ids = {int(t['token_id'])
                                 for t in (_json.loads(raw_map).get('tokens') or [])
                                 if t.get('token_id') is not None}
                    local_ids = {t.token_id for t in active_bm.tokens}
                    relay_map_ok = _relay_map_matches(relay_ids, local_ids)
                except (ValueError, TypeError, KeyError):
                    pass
            # Auto-repush: if the relay's stored map stays stale/missing across
            # several polls, re-send the live map (self-heals dropped pushes
            # and relay restarts — late joiners then get the current map).
            _maybe_repush_map(active_bm, raw_map)
        else:
            _map_resync['streak'] = 0

        # While the relay lags (map push in flight), skip its token rows ENTIRELY —
        # recording old-map seqs into the mirror would poison the reset the map
        # activation just performed.
        for tok in (payload.get('tokens', []) if relay_map_ok else []):
            label      = tok.get('label', '')
            x_pct      = tok.get('x_pct')
            y_pct      = tok.get('y_pct')
            token_type = tok.get('token_type', 'player')
            if not label or local_sid is None or x_pct is None or y_pct is None:
                continue
            try:
                tok_seq = int(tok['seq']) if tok.get('seq') is not None else None
            except (TypeError, ValueError):
                tok_seq = None

            # Update tblTokenPositions (relay mirror) and read the previously
            # processed seq BEFORE overwriting it.
            tp = tblTokenPositions.query.filter_by(session_id=local_sid, label=label).first()
            prev_seq = tp.relay_seq if tp else 0
            if tp:
                tp.x_pct      = x_pct
                tp.y_pct      = y_pct
                tp.updated_at = now
                if tok_seq is not None:
                    tp.relay_seq = tok_seq
            else:
                db.session.add(tblTokenPositions(
                    session_id  = local_sid,
                    label       = label,
                    x_pct       = x_pct,
                    y_pct       = y_pct,
                    token_type  = token_type,
                    updated_at  = now,
                    relay_seq   = tok_seq or 0,
                ))

            # Update tblBattleMapTokens so the local battlemap poll sees relay moves.
            if active_bm and relay_map_ok and token_type == 'player':
                char = tblCharacters.query.filter_by(name=label, active=1).first()
                if char:
                    bm_tok = tblBattleMapTokens.query.filter_by(
                        map_id=active_bm.map_id, entity_type='player', entity_id=char.character_id
                    ).first()
                    if bm_tok:
                        if not _should_apply_relay_pos(tok_seq, prev_seq,
                                                       tok.get('updated_at', ''),
                                                       bm_tok.updated_at or ''):
                            continue
                        bm_tok.col        = max(0, min(active_bm.grid_cols - 1,
                                                       round(x_pct * (active_bm.grid_cols - 1))))
                        bm_tok.row        = max(0, min(active_bm.grid_rows - 1,
                                                       round(y_pct * (active_bm.grid_rows - 1))))
                        bm_tok.updated_at = bm_tok_ts

        # --- roll log (relay roll_log array) ---
        # Relay roll shape: { id, session_id, player_name, roll_expr, result, breakdown, rolled_at }
        # De-dupe on the relay's UNIQUE roll id so fast or identical rolls are never
        # dropped (the old value/second-timestamp match collapsed same-second and
        # same-result rolls into one). Fall back to the fuzzy match only for a relay
        # that sends no id.
        import re as _re
        roll_cleared_at = appsettingGet('relay_roll_cleared_at', '')
        for roll in payload.get('roll_log', []):
            rolled_at = roll.get('rolled_at', '')
            if not rolled_at or local_sid is None:
                continue
            if roll_cleared_at and rolled_at <= roll_cleared_at:
                continue

            try:
                rid = int(roll['id']) if roll.get('id') is not None else None
            except (TypeError, ValueError, KeyError):
                rid = None

            player_name = roll.get('player_name', '')
            relay_expr  = roll.get('roll_expr', '')
            relay_total = roll.get('result', 0)

            # tblRollLog — full history. Dedup by relay id when present, else timestamp.
            if rid is not None:
                log_exists = tblRollLog.query.filter_by(session_id=local_sid, relay_roll_id=rid).first()
            else:
                log_exists = tblRollLog.query.filter_by(
                    session_id=local_sid, player_name=player_name, rolled_at=rolled_at).first()
            if not log_exists:
                db.session.add(tblRollLog(
                    session_id    = local_sid,
                    player_name   = player_name,
                    roll_expr     = relay_expr,
                    result        = relay_total,
                    breakdown     = roll.get('breakdown', ''),
                    rolled_at     = rolled_at,
                    relay_roll_id = rid,
                ))
                if tblRollLog.query.filter_by(session_id=local_sid).count() > 500:
                    oldest = (tblRollLog.query
                              .filter_by(session_id=local_sid)
                              .order_by(tblRollLog.id)
                              .first())
                    if oldest:
                        db.session.delete(oldest)

            # tblDiceRolls — the 50-roll display feed. Store the roll time in LOCAL
            # wall-clock (relay sends UTC) so it interleaves correctly with local rolls.
            ts_norm = _relay_ts_to_local(rolled_at)

            # Parse expr_base + label. Portal format: "{count}d{sides}{mod} [{mode}] {label}"
            _m = _re.match(
                r'^(\d*d\d+(?:[+-]\d+)?)'
                r'(?:\s*\[(?:advantage|disadvantage)\])?'
                r'(?:\s+(.+))?$',
                relay_expr, _re.IGNORECASE
            )
            if _m:
                expr_base  = _m.group(1) or ''
                roll_label = (_m.group(2) or '').strip()
            else:
                expr_base  = relay_expr.split()[0] if relay_expr else ''
                roll_label = ''

            if rid is not None:
                # Already recorded (as a relay roll, or as a claimed local echo)?
                if tblDiceRolls.query.filter_by(relay_roll_id=rid).first():
                    continue
                # Echo of a LOCAL roll we already show? Claim the most recent unclaimed
                # local row with the same signature instead of adding a duplicate. This
                # suppresses local-broadcast echoes WITHOUT dropping genuinely distinct
                # relay rolls (which each carry their own unique id).
                echo = (tblDiceRolls.query
                        .filter_by(char_name=player_name, total=relay_total, relay_roll_id=None)
                        .filter(tblDiceRolls.expression == expr_base)
                        .order_by(tblDiceRolls.roll_id.desc())
                        .first())
                if echo:
                    echo.relay_roll_id = rid
                    continue
            else:
                # Legacy relay with no id: original fuzzy dedup (timestamp, then value).
                existing_dr = tblDiceRolls.query.filter_by(char_name=player_name, rolled_at=ts_norm).first()
                if not existing_dr:
                    existing_dr = (tblDiceRolls.query
                        .filter_by(char_name=player_name, total=relay_total)
                        .filter(tblDiceRolls.expression == expr_base)
                        .first())
                if existing_dr:
                    continue

            # New relay roll → add it to the feed.
            breakdown_str = roll.get('breakdown', '')
            try:
                dice_list = [int(x.strip()) for x in breakdown_str.split(',') if x.strip()]
            except (ValueError, AttributeError):
                dice_list = []
            db.session.add(tblDiceRolls(
                char_name     = player_name,
                expression    = expr_base or relay_expr,
                label         = roll_label,
                dice_json     = _json.dumps(dice_list),
                modifier      = 0,
                total         = relay_total,
                adv_mode      = 'normal',
                rolled_at     = ts_norm,
                relay_roll_id = rid,
            ))
            db.session.flush()
            old = db.session.query(tblDiceRolls.roll_id).order_by(
                tblDiceRolls.roll_id.desc()).offset(50).all()
            if old:
                tblDiceRolls.query.filter(
                    tblDiceRolls.roll_id.in_([r[0] for r in old])
                ).delete(synchronize_session=False)

    except Exception as exc:
        log.warning('Relay token/roll sync error (mutations still processed): %s', exc)
        db.session.rollback()

    # --- character HP ---
    # Intentionally NOT copied from the relay. Local Flask is the single authority
    # for HP. Player HP changes arrive as `hp_delta` mutations (applied below) and
    # are pushed back to the relay; the relay never originates HP. Copying relay HP
    # into local here would let the relay win a conflict, violating local-authority.

    # --- character mutations (relay player sheet changes) ---
    # Idempotency ledger: if the ack POST below ever fails, the relay re-serves
    # the same mutations on the next poll. Without a ledger they would apply
    # again (an hp_delta would hit twice). Already-seen IDs are skipped but
    # still re-acked so the relay eventually marks them applied.
    pending_mutations = payload.get('pending_mutations', [])
    applied_ids    = []
    changed_chars  = set()  # character_id values that need push_character_and_broadcast
    # The ledger is only meaningful within ONE relay session: a new session (or
    # a relay redeploy with a fresh database) restarts mutation ids at 1, and
    # stale ledger entries would silently swallow-and-ack those fresh mutations.
    if appsettingGet('relay_applied_ledger_session', '') != session_id:
        _applied_ledger_save(set(), [])          # reset to empty
        appsettingSet('relay_applied_ledger_session', session_id)
        ledger = set()
    else:
        ledger = _applied_ledger_load()
    newly_applied  = []

    for mut in pending_mutations:
        if mut.get('applied'):
            continue
        mut_id         = mut.get('id')
        player_name    = mut.get('player_name', '')
        mutation_type  = mut.get('mutation_type', '')

        if mut_id is not None and mut_id in ledger:
            applied_ids.append(mut_id)   # re-ack only; do NOT re-apply
            continue

        try:
            data = _json.loads(mut.get('mutation_data', '{}'))
        except (ValueError, TypeError):
            data = {}

        char = tblCharacters.query.filter_by(name=player_name, active=1).first()
        if not char:
            applied_ids.append(mut_id)
            if mut_id is not None:
                newly_applied.append(mut_id)
            continue

        try:
            _apply_mutation(char, mutation_type, data, relay_url, db)
            changed_chars.add(char.character_id)
        except Exception as exc:
            log.warning('Mutation apply error (id=%s type=%s): %s', mut_id, mutation_type, exc)
        applied_ids.append(mut_id)
        if mut_id is not None:
            newly_applied.append(mut_id)

    db.session.commit()

    # Persist the ledger AFTER the mutation commit but BEFORE the ack attempt,
    # so an ack failure (the common case this protects against) can never lead
    # to a double-apply on the next poll.
    if newly_applied:
        _applied_ledger_save(ledger, newly_applied)

    # Ack applied mutations on the relay server
    if applied_ids:
        try:
            requests.post(
                relay_url.rstrip('/') + f'/api/v1/session/{session_id}/mutations/ack',
                json={'mutation_ids': applied_ids},
                headers={'X-Relay-Secret': secret, 'Content-Type': 'application/json'},
                timeout=5,
            )
        except Exception as exc:
            log.warning('Mutation ack failed: %s', exc)

    # Push updated characters back to relay so portal sees authoritative sheet
    if changed_chars:
        import relay_broadcaster
        for char_id in changed_chars:
            char = db.session.get(tblCharacters, char_id)
            if char:
                relay_broadcaster.push_character_and_broadcast(char)

    appsettingSet('relay_last_sync', now)

    # Self-healing resync: a recorded push drop means the broadcaster gave up
    # on something while the relay was unreachable — the party on the portal
    # may be stale. This poll just succeeded, so contact is back: re-push the
    # full party/users/library ONCE and clear the marker (re-armed only by the
    # next drop, so this never turns into a per-poll full push).
    if (appsettingGet('relay_push_last_drop', '') or '').strip():
        appsettingSet('relay_push_last_drop', '')
        try:
            import relay_broadcaster
            relay_broadcaster.push_all_characters()
            relay_broadcaster.push_session_users()
            relay_broadcaster.push_library()
            log.info('Relay contact restored after a dropped push — full party resync queued.')
        except Exception as exc:
            log.warning('Post-drop resync failed (will re-arm on next drop): %s', exc)


# Whitelist of tblCharacters columns that a relay player may update via attr_save
_ATTR_WHITELIST = frozenset({
    'ac', 'speed', 'initiative_bonus', 'passive_perception',
    'str_val', 'dex_val', 'con_val', 'int_val', 'wis_val', 'cha_val',
    'gold', 'silver', 'copper', 'level',
    'char_class', 'subclass', 'race', 'background',
})


def _apply_mutation(char, mutation_type, data, relay_url, db):
    """Dispatch a single mutation onto the SQLAlchemy character object (not yet committed)."""
    from models.ttrpg import (
        tblCharacterConditions, tblCharacterFeats, tblCharacterResources,
        tblCharacterSkills, tblCharacterInventory, tblCharacterNotes,
        tblCharacterWeapons, tblCharacterArmor, tblCharacterSpells,
    )
    from datetime import datetime as _dt
    _now_str = _dt.utcnow().strftime('%Y-%m-%d %H:%M:%S')

    if mutation_type == 'hp_delta':
        # Local is the authority for HP: apply the player's delta here, clamped
        # against the local hp_max. The result is pushed back to the relay/portal
        # via push_character_and_broadcast (character_sheet_updated).
        delta = int(data.get('delta', 0))
        cur = char.hp_current or 0
        mx  = char.hp_max or 1
        char.hp_current = max(0, min(mx, cur + delta))

    elif mutation_type == 'condition_add':
        cname = data.get('condition', '')
        if cname and not any(c.condition_name == cname for c in char.conditions):
            db.session.add(tblCharacterConditions(
                character_id=char.character_id, condition_name=cname,
                notes='', created_at=_now_str,
            ))

    elif mutation_type == 'condition_remove':
        cname = data.get('condition', '')
        for c in list(char.conditions):
            if c.condition_name == cname:
                db.session.delete(c)

    elif mutation_type == 'feat_add':
        fname = data.get('feat_name', '')
        if fname:
            order = max((f.order_by for f in char.feats), default=-1) + 1
            db.session.add(tblCharacterFeats(
                character_id=char.character_id, feat_name=fname,
                description=data.get('description', ''), order_by=order,
            ))

    elif mutation_type == 'feat_save':
        old_name = data.get('feat_name', '')
        for f in char.feats:
            if f.feat_name == old_name:
                f.feat_name   = data.get('new_name', old_name)
                f.description = data.get('description', f.description)
                break

    elif mutation_type == 'feat_remove':
        fname = data.get('feat_name', '')
        for f in list(char.feats):
            if f.feat_name == fname:
                db.session.delete(f)
                break

    elif mutation_type == 'resource_add':
        rname = data.get('resource_name', '')
        if rname:
            order = max((r.order_by for r in char.resources), default=-1) + 1
            db.session.add(tblCharacterResources(
                character_id=char.character_id, resource_name=rname,
                current_val=int(data.get('current_val', 0)),
                max_val=int(data.get('max_val', 0)),
                order_by=order,
            ))

    elif mutation_type == 'resource_set':
        rname = data.get('resource_name', '')
        for r in char.resources:
            if r.resource_name == rname:
                r.current_val = max(0, min(r.max_val, int(data.get('current_val', r.current_val))))
                break

    elif mutation_type == 'resource_save':
        old_name = data.get('resource_name', '') or data.get('old_name', '')
        for r in char.resources:
            if r.resource_name == old_name:
                r.resource_name = data.get('new_name', old_name)
                r.current_val   = int(data.get('current_val', r.current_val))
                r.max_val       = int(data.get('max_val', r.max_val))
                break

    elif mutation_type == 'resource_delete':
        rname = data.get('resource_name', '')
        for r in list(char.resources):
            if r.resource_name == rname:
                db.session.delete(r)
                break

    elif mutation_type == 'skill_add':
        sname = data.get('skill_name', '')
        if sname and not any(s.skill_name == sname for s in char.skills):
            order = max((s.order_by for s in char.skills), default=-1) + 1
            db.session.add(tblCharacterSkills(
                character_id=char.character_id,
                skill_name=sname,
                bonus=int(data.get('bonus', 0)),
                proficient=int(bool(data.get('proficient', False))),
                order_by=order,
            ))

    elif mutation_type == 'skill_remove':
        sname = data.get('skill_name', '')
        for s in list(char.skills):
            if s.skill_name == sname:
                db.session.delete(s)
                break

    elif mutation_type == 'skill_save':
        sname = data.get('skill_name', '')
        for s in char.skills:
            if s.skill_name == sname:
                if 'new_name'   in data: s.skill_name = data['new_name']
                if 'bonus'      in data: s.bonus      = int(data['bonus'])
                if 'proficient' in data: s.proficient = int(bool(data['proficient']))
                break

    elif mutation_type == 'inventory_add':
        iname = data.get('item_name', '')
        if iname:
            order = max((i.order_by for i in char.inventory), default=-1) + 1
            db.session.add(tblCharacterInventory(
                character_id=char.character_id, item_name=iname,
                quantity=int(data.get('quantity', 1)),
                weight=str(data.get('weight', '')),
                notes=data.get('notes', ''),
                equipped=int(bool(data.get('equipped', False))),
                order_by=order,
            ))

    elif mutation_type == 'inventory_save':
        old_name = data.get('item_name', '')
        for i in char.inventory:
            if i.item_name == old_name:
                i.item_name = data.get('new_name', old_name)
                i.quantity  = int(data.get('quantity', i.quantity))
                i.weight    = str(data.get('weight', i.weight))
                i.notes     = data.get('notes', i.notes)
                i.equipped  = int(bool(data.get('equipped', bool(i.equipped))))
                break

    elif mutation_type == 'inventory_remove':
        iname = data.get('item_name', '')
        for i in list(char.inventory):
            if i.item_name == iname:
                db.session.delete(i)
                break

    elif mutation_type == 'note_add':
        text = data.get('text', '')
        if text:
            created = data.get('created_at') or _now_str
            db.session.add(tblCharacterNotes(
                character_id=char.character_id, note_text=text, created_at=created,
            ))

    elif mutation_type == 'note_save':
        created = data.get('created_at', '')
        for n in char.notes:
            if n.created_at == created:
                n.note_text = data.get('text', n.note_text)
                break

    elif mutation_type == 'note_remove':
        created = data.get('created_at', '')
        text    = data.get('text', '')
        for n in list(char.notes):
            if (created and n.created_at == created) or (text and n.note_text == text):
                db.session.delete(n)
                break

    elif mutation_type == 'weapon_add':
        wname = data.get('weapon_name', '')
        if wname:
            order = max((w.order_by for w in char.weapons), default=-1) + 1
            db.session.add(tblCharacterWeapons(
                character_id=char.character_id, weapon_name=wname,
                weapon_category=data.get('weapon_category', ''),
                weapon_range=data.get('weapon_range', ''),
                damage_dice=data.get('damage_dice', ''),
                damage_type=data.get('damage_type', ''),
                two_handed_damage_dice=data.get('two_handed_damage_dice', ''),
                two_handed_damage_type=data.get('two_handed_damage_type', ''),
                range_normal=int(data.get('range_normal', 0)),
                range_long=int(data.get('range_long', 0)),
                attack_bonus=int(data.get('attack_bonus', 0)),
                damage_bonus=int(data.get('damage_bonus', 0)),
                properties=data.get('properties', ''),
                notes=data.get('notes', ''),
                equipped=int(bool(data.get('equipped', False))),
                order_by=order,
            ))

    elif mutation_type == 'weapon_save':
        old_name = data.get('weapon_name', '')
        for w in char.weapons:
            if w.weapon_name == old_name:
                w.weapon_name            = data.get('new_name', old_name)
                w.weapon_category        = data.get('weapon_category', w.weapon_category)
                w.weapon_range           = data.get('weapon_range', w.weapon_range)
                w.damage_dice            = data.get('damage_dice', w.damage_dice)
                w.damage_type            = data.get('damage_type', w.damage_type)
                w.two_handed_damage_dice = data.get('two_handed_damage_dice', w.two_handed_damage_dice)
                w.two_handed_damage_type = data.get('two_handed_damage_type', w.two_handed_damage_type)
                w.range_normal           = int(data.get('range_normal', w.range_normal))
                w.range_long             = int(data.get('range_long', w.range_long))
                w.attack_bonus           = int(data.get('attack_bonus', w.attack_bonus))
                w.damage_bonus           = int(data.get('damage_bonus', w.damage_bonus))
                w.properties             = data.get('properties', w.properties)
                w.notes                  = data.get('notes', w.notes)
                w.equipped               = int(bool(data.get('equipped', bool(w.equipped))))
                break

    elif mutation_type == 'weapon_remove':
        wname = data.get('weapon_name', '')
        for w in list(char.weapons):
            if w.weapon_name == wname:
                db.session.delete(w)
                break

    elif mutation_type == 'armor_add':
        aname = data.get('armor_name', '')
        if aname:
            order = max((a.order_by for a in char.armor), default=-1) + 1
            mdb = data.get('max_dex_bonus')
            db.session.add(tblCharacterArmor(
                character_id=char.character_id, armor_name=aname,
                armor_category=data.get('armor_category', ''),
                armor_class_base=int(data.get('ac_base', 0)),
                dex_bonus=int(bool(data.get('dex_bonus', False))),
                max_dex_bonus=int(mdb) if mdb is not None else None,
                ac_bonus=int(data.get('ac_bonus', 0)),
                notes=data.get('notes', ''),
                equipped=int(bool(data.get('equipped', False))),
                order_by=order,
            ))

    elif mutation_type == 'armor_save':
        old_name = data.get('armor_name', '')
        for a in char.armor:
            if a.armor_name == old_name:
                a.armor_name       = data.get('new_name', old_name)
                a.armor_category   = data.get('armor_category', a.armor_category)
                a.armor_class_base = int(data.get('ac_base', a.armor_class_base))
                a.dex_bonus        = int(bool(data.get('dex_bonus', bool(a.dex_bonus))))
                if 'max_dex_bonus' in data:
                    mdb = data['max_dex_bonus']
                    a.max_dex_bonus = int(mdb) if mdb is not None else None
                a.ac_bonus         = int(data.get('ac_bonus', a.ac_bonus))
                a.notes            = data.get('notes', a.notes)
                a.equipped         = int(bool(data.get('equipped', bool(a.equipped))))
                break

    elif mutation_type == 'armor_remove':
        aname = data.get('armor_name', '')
        for a in list(char.armor):
            if a.armor_name == aname:
                db.session.delete(a)
                break

    elif mutation_type == 'spell_add':
        sname = data.get('spell_name', '')
        if sname:
            order = max((s.order_by for s in char.spells), default=-1) + 1
            db.session.add(tblCharacterSpells(
                character_id=char.character_id, spell_name=sname,
                spell_level=int(data.get('spell_level', 0)),
                school=data.get('school', ''),
                prepared=int(bool(data.get('prepared', False))),
                notes=data.get('notes', ''),
                order_by=order,
            ))

    elif mutation_type == 'spell_save':
        sname = data.get('spell_name', '')
        for s in char.spells:
            if s.spell_name == sname:
                if 'prepared' in data: s.prepared = int(bool(data['prepared']))
                if 'notes'    in data: s.notes    = data['notes']
                break

    elif mutation_type == 'spell_remove':
        sname = data.get('spell_name', '')
        for s in list(char.spells):
            if s.spell_name == sname:
                db.session.delete(s)
                break

    elif mutation_type == 'attr_save':
        _txt_keys = {'char_class', 'subclass', 'race', 'background'}
        for key, val in data.items():
            if key in _ATTR_WHITELIST:
                if key in _txt_keys:
                    setattr(char, key, str(val) if val is not None else '')
                else:
                    cur = getattr(char, key, None)
                    setattr(char, key, type(cur)(val) if cur is not None else int(val))

    elif mutation_type == 'portrait_upload':
        portrait_rel = data.get('portrait_url', '')
        if portrait_rel and portrait_rel.startswith('/portraits/'):
            _download_portrait(char, relay_url, portrait_rel)


def _download_portrait(char, relay_url, portrait_rel):
    """Download a relay portrait and save it locally, updating char.portrait_path."""
    import os, requests as _req
    from flask import current_app
    filename = portrait_rel.split('/')[-1]
    try:
        portraits_dir = os.path.join(current_app.root_path, 'static', 'uploads', 'portraits')
        os.makedirs(portraits_dir, exist_ok=True)
        local_path = os.path.join(portraits_dir, filename)
        full_url   = relay_url.rstrip('/') + portrait_rel
        resp = _req.get(full_url, timeout=15)
        if resp.ok:
            with open(local_path, 'wb') as f:
                f.write(resp.content)
            char.portrait_path = filename
    except Exception as exc:
        log.warning('Portrait download failed (%s): %s', portrait_rel, exc)
