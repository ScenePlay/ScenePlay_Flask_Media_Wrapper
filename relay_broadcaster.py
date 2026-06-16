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


def _post(path, payload, cfg, timeout=5):
    import requests
    url = cfg['url'].rstrip('/') + path
    headers = {'X-Relay-Secret': cfg['secret'], 'Content-Type': 'application/json'}
    requests.post(url, json=payload, headers=headers, timeout=timeout)


def _fire(fn):
    threading.Thread(target=fn, daemon=True).start()


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
        try:
            _post(f'/api/v1/session/{cfg["session_id"]}/push-roll', payload, cfg)
        except Exception as e:
            log.warning('relay broadcast_roll failed: %s', e)

    _fire(_go)


def _battlemap_data(filename):
    """Return (base64_data, ext) for a battlemap bg image, or (None, None).

    Only still images are embedded so a remote relay can write the file itself;
    video backgrounds (and missing files) fall back to the URL."""
    if not filename:
        return None, None
    import base64, os
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    if ext not in ('png', 'jpg', 'jpeg', 'gif', 'webp'):
        return None, None
    try:
        from flask import current_app
        path = os.path.join(current_app.root_path, 'static', 'uploads', 'battlemaps', filename)
    except RuntimeError:
        return None, None
    if not os.path.exists(path):
        return None, None
    try:
        with open(path, 'rb') as f:
            return base64.b64encode(f.read()).decode('ascii'), ext
    except Exception:
        return None, None


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
    bg_data, bg_ext = _battlemap_data(bg_filename)
    if bg_data:
        # Embed the image inline as a data: URL. The remote map <img> reads
        # map.url, so the browser renders the bytes directly without reaching
        # this LAN server. (image_data/_ext kept for any relay-side handler.)
        mime = 'jpeg' if bg_ext == 'jpg' else bg_ext
        payload['map']['url']        = f'data:image/{mime};base64,{bg_data}'
        payload['map']['image_data'] = bg_data
        payload['map']['image_ext']  = bg_ext

    def _go():
        try:
            # Map pushes can carry an embedded background image — allow a generous
            # upload window so large maps aren't cut off on slow home uplinks.
            _post('/api/v1/session/push', payload, cfg, timeout=60)
        except Exception as e:
            log.warning('relay broadcast_map_update failed: %s', e)

    _fire(_go)


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
        try:
            _post('/api/v1/token/move', body, cfg)
        except Exception as e:
            log.warning('relay broadcast_token_move failed: %s', e)

    _fire(_go)


def broadcast_token_health(token_id, hp_current, hp_max):
    """POST /api/v1/token/health  body: { token_id, hp_current, hp_max, session_id }"""
    cfg = _active()
    if not cfg:
        return
    body = {'token_id': str(token_id), 'hp_current': hp_current, 'hp_max': hp_max,
            'session_id': cfg['session_id']}

    def _go():
        try:
            _post('/api/v1/token/health', body, cfg)
        except Exception as e:
            log.warning('relay broadcast_token_health failed: %s', e)

    _fire(_go)


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
        try:
            _post(f'/api/v1/session/{cfg["session_id"]}/condition-update', body, cfg)
        except Exception as e:
            log.warning('relay broadcast_condition_update failed: %s', e)

    _fire(_go)


def _portrait_data(char):
    """Return (filename, base64_data) for the character portrait, or (None, None)."""
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
        with open(path, 'rb') as f:
            return char.portrait_path, base64.b64encode(f.read()).decode('ascii')
    except Exception:
        return None, None


def _char_to_payload(char):
    """Build the character dict expected by POST /api/v1/session/{id}/characters."""
    import json as _json
    sheet = {
        'name':               char.name,
        'class':              char.char_class,
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
    portrait_filename, portrait_b64 = _portrait_data(char)
    return {
        'player_name':     char.name,
        'username':        user.username      if user else '',
        'display_name':    user.display_name  if user else char.name,
        'password_hash':   user.password_hash if user else '',
        'portrait_url':    '',
        'portrait_data':   portrait_b64 or '',
        'portrait_ext':    portrait_filename.rsplit('.', 1)[-1] if portrait_filename else '',
        'sheet_json':      _json.dumps(sheet),
        'hp_current':      char.hp_current,
        'hp_max':          char.hp_max,
    }


def push_all_characters():
    """Push every active-session party member to the relay so they exist before login.

    Calls POST /api/v1/session/{session_id}/characters with GM secret.
    The relay upserts by player_name so this is safe to call repeatedly.
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

    if not characters:
        log.info('push_all_characters: party is empty')
        return

    payload = {'characters': characters}

    def _go():
        try:
            _post(f'/api/v1/session/{cfg["session_id"]}/characters', payload, cfg)
            log.info('push_all_characters: pushed %d characters', len(characters))
        except Exception as e:
            log.warning('push_all_characters failed: %s', e)

    _fire(_go)


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
        try:
            _post(f'/api/v1/session/{cfg["session_id"]}/characters', payload, cfg)
        except Exception as e:
            log.warning('push_character failed: %s', e)

    _fire(_go)


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
        try:
            _post(f'/api/v1/session/{cfg["session_id"]}/characters', payload, cfg)
            _post(f'/api/v1/session/{cfg["session_id"]}/character-sheet-broadcast',
                  {'player_name': player_name}, cfg)
        except Exception as e:
            log.warning('push_character_and_broadcast failed: %s', e)

    _fire(_go)


def push_library():
    """Push all D&D library tables to relay so portal can search them during character edit."""
    cfg = _active()
    if not cfg:
        return

    from models.ttrpg import (tblSpellsLibrary, tblFeatsLibrary, tblWeaponsLibrary,
                               tblArmorLibrary, tblEquipmentLibrary, tblSkillsLibrary,
                               tblRacesLibrary, tblClassesLibrary)

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
             'properties': w.properties or ''}
            for w in tblWeaponsLibrary.query.order_by(tblWeaponsLibrary.name).all()
        ],
        'armor': [
            {'name': a.name, 'category': a.armor_category or '',
             'ac_base': a.armor_class_base, 'dex_bonus': bool(a.dex_bonus),
             'max_dex_bonus': a.max_dex_bonus, 'str_minimum': a.str_minimum,
             'stealth_disadvantage': bool(a.stealth_disadvantage)}
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
    }

    def _go():
        try:
            _post(f'/api/v1/session/{cfg["session_id"]}/library', payload, cfg)
            log.info('push_library: pushed library data to relay')
        except Exception as e:
            log.warning('push_library failed: %s', e)

    _fire(_go)


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
