import os
import uuid
from datetime import datetime
from flask import (Blueprint, render_template, redirect, url_for,
                   request, flash, jsonify, current_app)
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from extensions import db
from models.ttrpg import (tblCharacters, tblCharacterResources,
                           tblCharacterConditions, tblCharacterInventory,
                           tblCharacterSkills, tblCharacterNotes,
                           tblCharacterFeats, tblCharacterArmor,
                           tblCharacterWeapons, tblCharacterSpells,
                           tblSessions, tblSessionParty,
                           tblRacesLibrary, tblClassesLibrary, tblDiceRolls,
                           tblFeaturesLibrary, tblClassLevelsLibrary)
from models.campaigns import tblcampaigns
from models.scenes import tblscenes
from models.ttrpg import tblSessionMonsters as _tblSessionMonsters
from routes.auth import dm_required
from routes.monsters import condition_texts
import relay_broadcaster

ttrpg = Blueprint('ttrpg', __name__, url_prefix='/ttrpg')

PORTRAIT_FOLDER = os.path.join('static', 'uploads', 'portraits')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}


# ── Relay sync: mirror every local character edit to the relay ────────────────
# During a web request, record which characters are touched (at flush time, which
# emits no SQL), then AFTER the response push them to the relay so player-facing
# data stays in sync — covering all edit routes (DM or player) in one place.
# The push (and its SQL) runs in after_request — normal request context — never
# inside a session event, so it can't disrupt a flush/commit. Best-effort: any
# failure is swallowed and never affects the local edit.
from sqlalchemy import event as _sa_event

_RELAY_CHAR_SUBITEMS = (
    tblCharacterResources, tblCharacterConditions, tblCharacterInventory,
    tblCharacterSkills, tblCharacterNotes, tblCharacterFeats,
    tblCharacterArmor, tblCharacterWeapons, tblCharacterSpells,
)


def _relay_collect_chars(session, flush_context):
    """after_flush(session, flush_context): record touched character ids.
    Web requests only; reads cached attributes only (emits no SQL)."""
    from flask import has_request_context
    if not has_request_context():
        return
    try:
        ids = session.info.setdefault('_relay_char_ids', set())
        for obj in set(session.new) | set(session.dirty) | set(session.deleted):
            if isinstance(obj, tblCharacters):
                if obj.character_id:
                    ids.add(obj.character_id)
            elif isinstance(obj, _RELAY_CHAR_SUBITEMS):
                cid = getattr(obj, 'character_id', None)
                if cid:
                    ids.add(cid)
    except Exception:
        pass


_sa_event.listen(db.session, 'after_flush', _relay_collect_chars)


@ttrpg.after_request
def _relay_push_dirty_chars(response):
    """After the response (commit done, normal context), push edited characters."""
    try:
        ids = db.session.info.pop('_relay_char_ids', None)
        if ids:
            for cid in ids:
                try:
                    char = db.session.get(tblCharacters, cid)
                    if char is not None:
                        relay_broadcaster.push_character_and_broadcast(char)
                except Exception:
                    pass
    except Exception:
        pass
    return response


def _allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


from routes._util import _now  # shared timestamp format (relay sync compares these strings)


# ── Dashboard ──────────────────────────────────────────────────────────────────

@ttrpg.route('/')
@login_required
def dashboard():
    if not current_user.is_dm():
        return redirect(url_for('ttrpg.my_character'))

    campaigns = tblcampaigns.query.order_by(tblcampaigns.campaign_name).all()
    sessions  = tblSessions.query.order_by(tblSessions.created_at.desc()).all()
    characters = tblCharacters.query.filter_by(active=1).order_by(tblCharacters.name).all()
    active_session = tblSessions.query.filter_by(status='active').first()

    # Campaign -> every character who has been in any of its sessions' parties
    # (comma-wrapped id strings for the dashboard's client-side filtering).
    camp_chars = {}
    for cid, chid in (db.session.query(tblSessions.campaign_id, tblSessionParty.character_id)
                      .join(tblSessionParty,
                            tblSessionParty.session_id == tblSessions.session_id)
                      .filter(tblSessions.campaign_id.isnot(None))
                      .distinct().all()):
        camp_chars.setdefault(cid, set()).add(chid)
    campaign_char_ids = {cid: ',' + ','.join(str(i) for i in sorted(ids)) + ','
                         for cid, ids in camp_chars.items()}

    return render_template('ttrpg/dashboard.html',
                           campaigns=campaigns,
                           sessions=sessions,
                           characters=characters,
                           campaign_char_ids=campaign_char_ids,
                           active_session=active_session)


# ── Characters — DM list ───────────────────────────────────────────────────────

@ttrpg.route('/characters')
@login_required
@dm_required
def characters():
    all_chars = (tblCharacters.query
                 .filter_by(active=1)
                 .order_by(tblCharacters.name)
                 .all())
    return render_template('ttrpg/characters.html', characters=all_chars)


# ── My Character — player landing ──────────────────────────────────────────────

@ttrpg.route('/my-character')
@login_required
def my_character():
    chars = (tblCharacters.query
             .filter_by(user_id=current_user.user_id, active=1)
             .order_by(tblCharacters.name)
             .all())
    # Find active battle map — show to any logged-in player when a map is live
    from models.ttrpg import tblBattleMaps
    active_map = None
    active_session = tblSessions.query.filter_by(status='active').first()
    if active_session:
        active_map = tblBattleMaps.query.filter_by(
            session_id=active_session.session_id, is_active=1).first()
    return render_template('ttrpg/my_characters.html', characters=chars, active_map=active_map)


# ── Character create ───────────────────────────────────────────────────────────

@ttrpg.route('/character/random')
@login_required
def character_random():
    """Roll a complete random character (level, stats, name, traits) as JSON
    for the create-character form to fill in."""
    from char_randgen import generate_character
    try:
        min_level = int(request.args.get('min_level', 1))
        max_level = int(request.args.get('max_level', 20))
    except ValueError:
        min_level, max_level = 1, 20
    genre = request.args.get('genre', 'fantasy')
    return jsonify(generate_character(min_level, max_level, genre=genre))


@ttrpg.route('/character/new', methods=['GET', 'POST'])
@login_required
def character_new():
    error = None
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        if not name:
            error = 'Character name is required.'
        else:
            char = tblCharacters(
                user_id    = current_user.user_id,
                name       = name,
                char_class = request.form.get('char_class', '').strip(),
                subclass   = request.form.get('subclass', '').strip(),
                race       = request.form.get('race', '').strip(),
                level      = int(request.form.get('level', 1) or 1),
                background = request.form.get('background', '').strip(),
                genre      = request.form.get('genre', 'fantasy').strip() or 'fantasy',
                hp_max     = int(request.form.get('hp_max', 0) or 0),
                hp_current = int(request.form.get('hp_max', 0) or 0),
                ac         = int(request.form.get('ac', 10) or 10),
                str_val    = int(request.form.get('str_val', 10) or 10),
                dex_val    = int(request.form.get('dex_val', 10) or 10),
                con_val    = int(request.form.get('con_val', 10) or 10),
                int_val    = int(request.form.get('int_val', 10) or 10),
                wis_val    = int(request.form.get('wis_val', 10) or 10),
                cha_val    = int(request.form.get('cha_val', 10) or 10),
                speed      = int(request.form.get('speed', 30) or 30),
                initiative_bonus   = int(request.form.get('initiative_bonus', 0) or 0),
                passive_perception = int(request.form.get('passive_perception', 10) or 10),
                gold   = int(request.form.get('gold', 0) or 0),
                silver = int(request.form.get('silver', 0) or 0),
                copper = int(request.form.get('copper', 0) or 0),
                active     = 1,
                created_at = _now(),
            )
            db.session.add(char)
            db.session.flush()  # get character_id before portrait save

            # Optional: drop the new character straight into a session's party.
            # DM only — party management is a DM concern everywhere else.
            added_to_session = None
            add_sid = request.form.get('add_session_id', '').strip()
            if add_sid.isdigit() and current_user.is_dm():
                sess = db.session.get(tblSessions, int(add_sid))
                if sess and sess.status in ('planning', 'active'):
                    db.session.add(tblSessionParty(
                        session_id=sess.session_id,
                        character_id=char.character_id,
                        joined_at=_now()))
                    added_to_session = sess

            # Personality/ideal/bond/flaw from the randomizer -> first note
            traits_note = request.form.get('traits_note', '').strip()
            if traits_note:
                db.session.add(tblCharacterNotes(
                    character_id=char.character_id,
                    note_text=traits_note,
                    created_at=_now(),
                ))

            # Portrait upload
            portrait = request.files.get('portrait')
            if portrait and portrait.filename and _allowed_file(portrait.filename):
                from routes._util import save_upload_downscaled
                filename = save_upload_downscaled(
                    portrait, os.path.join(current_app.root_path, PORTRAIT_FOLDER))
                char.portrait_path = filename

            db.session.commit()
            if added_to_session:
                # Party changed — mirror it to the relay (no-op unless the
                # active session is the one that gained the character).
                relay_broadcaster.push_all_characters()
                flash(f'"{char.name}" added to session '
                      f'#{added_to_session.session_number} {added_to_session.title}.')
            return redirect(url_for('ttrpg.character_sheet', character_id=char.character_id))

    from genre_packs import genre_labels, client_data
    open_sessions = (tblSessions.query
                     .filter(tblSessions.status.in_(['planning', 'active']))
                     .order_by(tblSessions.created_at.desc())
                     .all()) if current_user.is_dm() else []
    return render_template('ttrpg/character_new.html', error=error,
                           genre_options=genre_labels(),
                           genre_client_data=client_data(),
                           open_sessions=open_sessions)


# ── Class progression (synced from the D&D API's class level tables) ──────────

# class_specific counters that behave like spendable resources. Everything else
# in class_specific (dice sizes, passive numbers like aura range) is skipped.
_CLASS_RESOURCE_NAMES = {
    'rage_count':               'Rages',
    'ki_points':                'Ki Points',
    'sorcery_points':           'Sorcery Points',
    'channel_divinity_charges': 'Channel Divinity',
    'action_surges':            'Action Surge',
    'indomitable_uses':         'Indomitable',
}


def _class_progression(char):
    """(features, level_info) for the character's class at its current level.

    features: tblFeaturesLibrary rows for the base class, level <= char.level.
    level_info: {'prof_bonus', 'slots': {lvl: n}, 'cantrips_known',
                 'spells_known', 'counters': {label: n}} from the class level
    table, or None when the class/level isn't synced."""
    import json as _json
    from sqlalchemy import func
    cls = (char.char_class or '').strip()
    if not cls:
        return [], None
    sub = (getattr(char, 'subclass', '') or '').strip()
    feat_filter = (func.lower(tblFeaturesLibrary.class_name) == cls.lower())
    if sub:
        from sqlalchemy import or_
        subclass_match = or_(tblFeaturesLibrary.subclass_name == '',
                             func.lower(tblFeaturesLibrary.subclass_name) == sub.lower())
    else:
        subclass_match = (tblFeaturesLibrary.subclass_name == '')
    features = (tblFeaturesLibrary.query
                .filter(feat_filter, subclass_match,
                        tblFeaturesLibrary.level <= (char.level or 1))
                .order_by(tblFeaturesLibrary.level, tblFeaturesLibrary.name)
                .all())
    # Libraries synced before the same-name skip existed hold both editions of a
    # feature ('rage' + 'barbarian-rage', same display name). Collapse duplicates
    # per (level, name), keeping the fuller text.
    best = {}
    for f in features:
        key = (f.level, (f.name or '').lower(), (f.subclass_name or '').lower())
        if key not in best or len(f.description or '') > len(best[key].description or ''):
            best[key] = f
    features = sorted(best.values(), key=lambda f: (f.level, (f.name or '').lower()))
    row = (tblClassLevelsLibrary.query
           .filter(func.lower(tblClassLevelsLibrary.class_name) == cls.lower(),
                   tblClassLevelsLibrary.level == (char.level or 1))
           .first())
    level_info = None
    if row:
        try:
            slots = {int(k): v for k, v in _json.loads(row.spell_slots_json or '{}').items() if v}
        except Exception:
            slots = {}
        try:
            specific = _json.loads(row.class_specific_json or '{}')
        except Exception:
            specific = {}
        counters = {label: specific[key] for key, label in _CLASS_RESOURCE_NAMES.items()
                    if isinstance(specific.get(key), int) and specific[key] > 0}
        level_info = {
            'prof_bonus':     row.prof_bonus,
            'slots':          slots,
            'cantrips_known': row.cantrips_known,
            'spells_known':   row.spells_known,
            'counters':       counters,
        }
    return features, level_info


@ttrpg.route('/character/<int:character_id>/suggest-resources', methods=['POST'])
@login_required
def suggest_resources(character_id):
    """Create spell-slot / class-counter resources from the synced class level
    table. Only ADDS resources whose names don't exist yet — anything the
    player typed by hand is never touched or overwritten."""
    char = tblCharacters.query.get_or_404(character_id)
    if not current_user.is_dm() and char.user_id != current_user.user_id:
        return jsonify({'ok': False, 'error': 'forbidden'}), 403

    _, level_info = _class_progression(char)
    if not level_info:
        return jsonify({'ok': False,
                        'error': f'No synced class table for "{char.char_class}" level {char.level}. '
                                 f'Run Sync All on the API Settings page first.'}), 404

    existing = {(r.resource_name or '').strip().lower() for r in char.resources}
    order = max([r.order_by or 0 for r in char.resources], default=0)
    added = []

    wanted = [(f'Spell Slots L{lvl}', n) for lvl, n in sorted(level_info['slots'].items())]
    wanted += sorted(level_info['counters'].items())
    for name, count in wanted:
        if name.lower() in existing:
            continue
        order += 1
        db.session.add(tblCharacterResources(
            character_id=character_id, resource_name=name,
            current_val=count, max_val=count, order_by=order))
        added.append(name)
    db.session.commit()
    relay_broadcaster.push_character(char)
    return jsonify({'ok': True, 'added': added,
                    'message': (f'Added: {", ".join(added)}' if added
                                else 'Nothing to add — all suggested resources already exist.')})


# ── Character sheet — view ─────────────────────────────────────────────────────

@ttrpg.route('/character/<int:character_id>')
@login_required
def character_sheet(character_id):
    char = tblCharacters.query.get_or_404(character_id)
    if not current_user.is_dm() and char.user_id != current_user.user_id:
        flash('You do not have access to that character.')
        return redirect(url_for('ttrpg.my_character'))
    all_players = []
    if current_user.is_dm():
        from models.user import tblUsers
        all_players = tblUsers.query.filter_by(active=1).order_by(tblUsers.display_name).all()
    races_lib   = {r.name.lower(): r for r in tblRacesLibrary.query.all()}
    classes_lib = {c.name.lower(): c for c in tblClassesLibrary.query.all()}
    can_edit = current_user.is_dm() or char.user_id == current_user.user_id
    class_features, class_level_info = _class_progression(char)
    subclass_options = []
    if char.char_class:
        from sqlalchemy import func
        from models.ttrpg import tblSubclassesLibrary
        subclass_options = [s.name for s in tblSubclassesLibrary.query
                            .filter(func.lower(tblSubclassesLibrary.class_name)
                                    == char.char_class.strip().lower())
                            .order_by(tblSubclassesLibrary.name).all()]
    from models.ttrpg import tblWeaponPropertiesLibrary
    weapon_props = {w.name.lower(): w.description
                    for w in tblWeaponPropertiesLibrary.query.all() if w.description}

    # Genre skin for the AI portrait prompt (display labels + art direction)
    from genre_packs import get_pack, genre_display
    _pack = get_pack(getattr(char, 'genre', '') or '')
    genre_archetype, genre_species = genre_display(
        char.genre, char.char_class, char.race) if _pack else ('', '')
    genre_art = _pack['art_style'] if _pack else []
    genre_label = _pack['label'] if _pack else ''

    return render_template('ttrpg/character_sheet.html', char=char,
                           all_players=all_players, conditions=condition_texts(),
                           races_lib=races_lib, classes_lib=classes_lib,
                           class_features=class_features,
                           class_level_info=class_level_info,
                           subclass_options=subclass_options,
                           weapon_props=weapon_props,
                           genre_archetype=genre_archetype,
                           genre_species=genre_species,
                           genre_art=genre_art,
                           genre_label=genre_label,
                           can_edit=can_edit)


# ── Character sheet — inline field save (AJAX) ─────────────────────────────────

@ttrpg.route('/character/<int:character_id>/save-field', methods=['POST'])
@login_required
def save_field(character_id):
    char = tblCharacters.query.get_or_404(character_id)
    if not current_user.is_dm() and char.user_id != current_user.user_id:
        return jsonify({'ok': False, 'error': 'forbidden'}), 403

    data = request.get_json()
    field = data.get('field')
    value = data.get('value')

    int_fields = {'hp_current', 'hp_max', 'ac', 'str_val', 'dex_val', 'con_val',
                  'int_val', 'wis_val', 'cha_val', 'speed', 'initiative_bonus',
                  'passive_perception', 'gold', 'silver', 'copper', 'level'}
    text_fields = {'name', 'char_class', 'subclass', 'race', 'background'}

    if field in int_fields:
        setattr(char, field, int(value or 0))
    elif field in text_fields:
        setattr(char, field, str(value or ''))
    else:
        return jsonify({'ok': False, 'error': 'unknown field'}), 400

    db.session.commit()
    if field in ('hp_current', 'hp_max'):
        token_id = relay_broadcaster.find_token_id('player', char.character_id)
        if token_id:
            relay_broadcaster.broadcast_token_health(token_id, char.hp_current, char.hp_max)
    relay_broadcaster.push_character(char)
    return jsonify({'ok': True, 'hp_pct': char.hp_pct()})


# ── HP delta (apply damage / healing by amount) ───────────────────────────────

@ttrpg.route('/character/<int:character_id>/hp-delta', methods=['POST'])
@login_required
def hp_delta(character_id):
    char = tblCharacters.query.get_or_404(character_id)
    if not current_user.is_dm() and char.user_id != current_user.user_id:
        return jsonify({'ok': False, 'error': 'forbidden'}), 403
    data = request.get_json()
    delta = int(data.get('delta', 0))
    char.hp_current = max(0, min(char.hp_max, char.hp_current + delta))
    db.session.commit()
    token_id = relay_broadcaster.find_token_id('player', char.character_id)
    if token_id:
        relay_broadcaster.broadcast_token_health(token_id, char.hp_current, char.hp_max)
    relay_broadcaster.push_character(char)
    return jsonify({'ok': True, 'hp_current': char.hp_current, 'hp_pct': char.hp_pct()})


# ── Character condition add / remove ──────────────────────────────────────────

@ttrpg.route('/character/<int:character_id>/condition', methods=['POST'])
@login_required
def character_condition(character_id):
    char = tblCharacters.query.get_or_404(character_id)
    if not current_user.is_dm() and char.user_id != current_user.user_id:
        return jsonify({'ok': False, 'error': 'forbidden'}), 403
    data = request.get_json()
    action = data.get('action')
    condition = data.get('condition', '').strip()

    if action == 'add' and condition:
        if not any(c.condition_name == condition for c in char.conditions):
            db.session.add(tblCharacterConditions(
                character_id=character_id,
                condition_name=condition,
                created_at=_now(),
            ))
            db.session.commit()
    elif action == 'remove' and condition:
        cond = tblCharacterConditions.query.filter_by(
            character_id=character_id, condition_name=condition
        ).first()
        if cond:
            db.session.delete(cond)
            db.session.commit()

    conds = [c.condition_name for c in char.conditions]
    relay_broadcaster.broadcast_condition_update(conds, player_name=char.name)
    return jsonify({'ok': True, 'conditions': conds})


# ── Resource delta (spend / recover one pip) ───────────────────────────────────

@ttrpg.route('/resource/<int:resource_id>/delta', methods=['POST'])
@login_required
def resource_delta(resource_id):
    r = tblCharacterResources.query.get_or_404(resource_id)
    char = r.character
    if not current_user.is_dm() and char.user_id != current_user.user_id:
        return jsonify({'ok': False, 'error': 'forbidden'}), 403
    data = request.get_json()
    delta = int(data.get('delta', 0))
    r.current_val = max(0, min(r.max_val, r.current_val + delta))
    db.session.commit()
    return jsonify({'ok': True, 'current_val': r.current_val, 'max_val': r.max_val})


# ── Character edit (full form) ─────────────────────────────────────────────────

@ttrpg.route('/character/<int:character_id>/edit', methods=['GET', 'POST'])
@login_required
def character_edit(character_id):
    char = tblCharacters.query.get_or_404(character_id)
    if not current_user.is_dm() and char.user_id != current_user.user_id:
        flash('You do not have access to that character.')
        return redirect(url_for('ttrpg.my_character'))

    error = None
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        if not name:
            error = 'Character name is required.'
        else:
            char.name       = name
            char.char_class = request.form.get('char_class', '').strip()
            char.race       = request.form.get('race', '').strip()
            char.level      = int(request.form.get('level', char.level) or char.level)
            char.background = request.form.get('background', '').strip()
            char.hp_max     = int(request.form.get('hp_max', char.hp_max) or char.hp_max)
            char.hp_current = int(request.form.get('hp_current', char.hp_current) or char.hp_current)
            char.hp_current = max(0, min(char.hp_max, char.hp_current))
            char.ac         = int(request.form.get('ac', char.ac) or char.ac)
            char.str_val    = int(request.form.get('str_val', char.str_val) or char.str_val)
            char.dex_val    = int(request.form.get('dex_val', char.dex_val) or char.dex_val)
            char.con_val    = int(request.form.get('con_val', char.con_val) or char.con_val)
            char.int_val    = int(request.form.get('int_val', char.int_val) or char.int_val)
            char.wis_val    = int(request.form.get('wis_val', char.wis_val) or char.wis_val)
            char.cha_val    = int(request.form.get('cha_val', char.cha_val) or char.cha_val)
            char.speed      = int(request.form.get('speed', char.speed) or char.speed)
            char.initiative_bonus   = int(request.form.get('initiative_bonus', char.initiative_bonus) or 0)
            char.passive_perception = int(request.form.get('passive_perception', char.passive_perception) or char.passive_perception)
            char.gold   = int(request.form.get('gold', char.gold) or 0)
            char.silver = int(request.form.get('silver', char.silver) or 0)
            char.copper = int(request.form.get('copper', char.copper) or 0)

            portrait = request.files.get('portrait')
            if portrait and portrait.filename and _allowed_file(portrait.filename):
                if char.portrait_path:
                    old = os.path.join(current_app.root_path, PORTRAIT_FOLDER, char.portrait_path)
                    if os.path.exists(old):
                        os.remove(old)
                from routes._util import save_upload_downscaled
                filename = save_upload_downscaled(
                    portrait, os.path.join(current_app.root_path, PORTRAIT_FOLDER))
                char.portrait_path = filename

            db.session.commit()
            return redirect(url_for('ttrpg.character_sheet', character_id=char.character_id))

    return render_template('ttrpg/character_edit.html', char=char, error=error)


# ── Assign character to a different player (DM only) ──────────────────────────

@ttrpg.route('/character/<int:character_id>/assign', methods=['POST'])
@login_required
@dm_required
def character_assign(character_id):
    char = tblCharacters.query.get_or_404(character_id)
    new_user_id = request.form.get('user_id', type=int)
    if new_user_id:
        from models.user import tblUsers
        user = db.session.get(tblUsers, new_user_id)
        if user:
            char.user_id = new_user_id
            db.session.commit()
            # Reaches connected portals live (character_upserted with the new
            # username) — the old owner loses the sheet, the new owner gains
            # it, nobody re-logs. No-op unless char is in the active session.
            relay_broadcaster.push_character(char)
            flash(f'{char.name} reassigned to {user.display_name}.')
    return redirect(url_for('ttrpg.character_sheet', character_id=character_id))


# ── Portrait upload ────────────────────────────────────────────────────────────

@ttrpg.route('/character/<int:character_id>/portrait', methods=['POST'])
@login_required
def upload_portrait(character_id):
    char = tblCharacters.query.get_or_404(character_id)
    if not current_user.is_dm() and char.user_id != current_user.user_id:
        flash('Access denied.')
        return redirect(url_for('ttrpg.character_sheet', character_id=character_id))

    portrait = request.files.get('portrait')
    if portrait and portrait.filename and _allowed_file(portrait.filename):
        # Remove old portrait
        if char.portrait_path:
            old = os.path.join(current_app.root_path, PORTRAIT_FOLDER, char.portrait_path)
            if os.path.exists(old):
                os.remove(old)
        from routes._util import save_upload_downscaled
        filename = save_upload_downscaled(
            portrait, os.path.join(current_app.root_path, PORTRAIT_FOLDER))
        char.portrait_path = filename
        db.session.commit()
    return redirect(url_for('ttrpg.character_sheet', character_id=character_id))


@ttrpg.route('/character/<int:character_id>/portrait-paste', methods=['POST'])
@login_required
def portrait_paste(character_id):
    char = tblCharacters.query.get_or_404(character_id)
    if not current_user.is_dm() and char.user_id != current_user.user_id:
        return jsonify({'ok': False, 'error': 'forbidden'}), 403
    portrait = request.files.get('portrait')
    if not portrait:
        return jsonify({'ok': False, 'error': 'no file'}), 400
    if char.portrait_path:
        old = os.path.join(current_app.root_path, PORTRAIT_FOLDER, char.portrait_path)
        if os.path.exists(old):
            os.remove(old)
    # Through the shared Pillow pipeline like every other upload: downscale,
    # opaque->JPEG. (This endpoint used to save raw bytes as .png — the
    # source of multi-MB portraits.)
    from routes._util import save_upload_downscaled
    filename = save_upload_downscaled(
        portrait, os.path.join(current_app.root_path, PORTRAIT_FOLDER))
    char.portrait_path = filename
    db.session.commit()
    return jsonify({'ok': True, 'url': url_for('static', filename='uploads/portraits/' + filename)})


# ── Character delete ───────────────────────────────────────────────────────────

@ttrpg.route('/character/<int:character_id>/delete', methods=['POST'])
@login_required
@dm_required
def character_delete(character_id):
    char = tblCharacters.query.get_or_404(character_id)
    char.active = 0
    db.session.commit()
    flash(f'Character "{char.name}" removed.')
    return redirect(url_for('ttrpg.characters'))


# ── Resources CRUD (AJAX) ──────────────────────────────────────────────────────

@ttrpg.route('/character/<int:character_id>/resources', methods=['POST'])
@login_required
def resource_add(character_id):
    char = tblCharacters.query.get_or_404(character_id)
    if not current_user.is_dm() and char.user_id != current_user.user_id:
        return jsonify({'ok': False}), 403
    data = request.get_json()
    r = tblCharacterResources(
        character_id  = character_id,
        resource_name = data.get('resource_name', '').strip(),
        current_val   = int(data.get('current_val', 0) or 0),
        max_val       = int(data.get('max_val', 0) or 0),
        order_by      = len(char.resources),
    )
    db.session.add(r)
    db.session.commit()
    return jsonify({'ok': True, 'resource_id': r.resource_id})


@ttrpg.route('/resource/<int:resource_id>', methods=['POST', 'DELETE'])
@login_required
def resource_update(resource_id):
    r = tblCharacterResources.query.get_or_404(resource_id)
    char = r.character
    if not current_user.is_dm() and char.user_id != current_user.user_id:
        return jsonify({'ok': False}), 403
    if request.method == 'DELETE':
        db.session.delete(r)
        db.session.commit()
        return jsonify({'ok': True})
    data = request.get_json()
    r.resource_name = data.get('resource_name', r.resource_name)
    r.current_val   = int(data.get('current_val', r.current_val) or 0)
    r.max_val       = int(data.get('max_val', r.max_val) or 0)
    db.session.commit()
    return jsonify({'ok': True})


# ── Skills CRUD (AJAX) ─────────────────────────────────────────────────────────

@ttrpg.route('/character/<int:character_id>/skills', methods=['POST'])
@login_required
def skill_add(character_id):
    char = tblCharacters.query.get_or_404(character_id)
    if not current_user.is_dm() and char.user_id != current_user.user_id:
        return jsonify({'ok': False}), 403
    data = request.get_json()
    s = tblCharacterSkills(
        character_id = character_id,
        skill_name   = data.get('skill_name', '').strip(),
        bonus        = int(data.get('bonus', 0) or 0),
        proficient   = int(data.get('proficient', 0) or 0),
        order_by     = len(char.skills),
    )
    db.session.add(s)
    db.session.commit()
    return jsonify({'ok': True, 'skill_id': s.skill_id})


@ttrpg.route('/skill/<int:skill_id>', methods=['POST', 'DELETE'])
@login_required
def skill_update(skill_id):
    s = tblCharacterSkills.query.get_or_404(skill_id)
    char = s.character
    if not current_user.is_dm() and char.user_id != current_user.user_id:
        return jsonify({'ok': False}), 403
    if request.method == 'DELETE':
        db.session.delete(s)
        db.session.commit()
        return jsonify({'ok': True})
    data = request.get_json()
    s.skill_name = data.get('skill_name', s.skill_name)
    s.bonus      = int(data.get('bonus', s.bonus) or 0)
    s.proficient = int(data.get('proficient', s.proficient) or 0)
    db.session.commit()
    return jsonify({'ok': True})


# ── Inventory CRUD (AJAX) ──────────────────────────────────────────────────────

@ttrpg.route('/character/<int:character_id>/inventory', methods=['POST'])
@login_required
def inventory_add(character_id):
    char = tblCharacters.query.get_or_404(character_id)
    if not current_user.is_dm() and char.user_id != current_user.user_id:
        return jsonify({'ok': False}), 403
    data = request.get_json()
    item = tblCharacterInventory(
        character_id = character_id,
        item_name    = data.get('item_name', '').strip(),
        quantity     = int(data.get('quantity', 1) or 1),
        weight       = data.get('weight', ''),
        notes        = data.get('notes', ''),
        equipped     = int(data.get('equipped', 0) or 0),
        order_by     = len(char.inventory),
    )
    db.session.add(item)
    db.session.commit()
    return jsonify({'ok': True, 'item_id': item.item_id})


@ttrpg.route('/inventory/<int:item_id>', methods=['POST', 'DELETE'])
@login_required
def inventory_update(item_id):
    item = tblCharacterInventory.query.get_or_404(item_id)
    char = item.character
    if not current_user.is_dm() and char.user_id != current_user.user_id:
        return jsonify({'ok': False}), 403
    if request.method == 'DELETE':
        db.session.delete(item)
        db.session.commit()
        return jsonify({'ok': True})
    data = request.get_json()
    item.item_name = data.get('item_name', item.item_name)
    item.quantity  = int(data.get('quantity', item.quantity) or 1)
    item.weight    = data.get('weight', item.weight)
    item.notes     = data.get('notes', item.notes)
    item.equipped  = int(data.get('equipped', item.equipped) or 0)
    db.session.commit()
    return jsonify({'ok': True})


# ── Notes CRUD (AJAX) ──────────────────────────────────────────────────────────

@ttrpg.route('/character/<int:character_id>/notes', methods=['POST'])
@login_required
def note_add(character_id):
    char = tblCharacters.query.get_or_404(character_id)
    if not current_user.is_dm() and char.user_id != current_user.user_id:
        return jsonify({'ok': False}), 403
    data = request.get_json()
    note = tblCharacterNotes(
        character_id = character_id,
        note_text    = data.get('note_text', '').strip(),
        created_at   = _now(),
    )
    db.session.add(note)
    db.session.commit()
    return jsonify({'ok': True, 'note_id': note.note_id, 'created_at': note.created_at})


@ttrpg.route('/note/<int:note_id>', methods=['POST', 'DELETE'])
@login_required
def note_update(note_id):
    note = tblCharacterNotes.query.get_or_404(note_id)
    char = note.character
    if not current_user.is_dm() and char.user_id != current_user.user_id:
        return jsonify({'ok': False}), 403
    if request.method == 'DELETE':
        db.session.delete(note)
        db.session.commit()
        return jsonify({'ok': True})
    data = request.get_json()
    note.note_text = data.get('note_text', note.note_text).strip()
    db.session.commit()
    return jsonify({'ok': True})


# ── Feats CRUD (AJAX) ──────────────────────────────────────────────────────────

@ttrpg.route('/character/<int:character_id>/feats', methods=['POST'])
@login_required
def feat_add(character_id):
    char = tblCharacters.query.get_or_404(character_id)
    if not current_user.is_dm() and char.user_id != current_user.user_id:
        return jsonify({'ok': False}), 403
    data = request.get_json()
    feat_name = data.get('feat_name', '').strip()
    if not feat_name:
        return jsonify({'ok': False, 'error': 'Feat name is required'}), 400
    feat = tblCharacterFeats(
        character_id = character_id,
        feat_name    = feat_name,
        description  = data.get('description', '').strip(),
        order_by     = len(char.feats),
    )
    db.session.add(feat)
    db.session.commit()
    return jsonify({'ok': True, 'feat_id': feat.feat_id})


@ttrpg.route('/feat/<int:feat_id>', methods=['POST', 'DELETE'])
@login_required
def feat_update(feat_id):
    feat = tblCharacterFeats.query.get_or_404(feat_id)
    char = feat.character
    if not current_user.is_dm() and char.user_id != current_user.user_id:
        return jsonify({'ok': False}), 403
    if request.method == 'DELETE':
        db.session.delete(feat)
        db.session.commit()
        return jsonify({'ok': True})
    data = request.get_json()
    feat.feat_name   = data.get('feat_name', feat.feat_name).strip() or feat.feat_name
    feat.description = data.get('description', feat.description)
    db.session.commit()
    return jsonify({'ok': True})


# ── Character Armor CRUD (AJAX) ────────────────────────────────────────────────

@ttrpg.route('/character/<int:character_id>/armor', methods=['POST'])
@login_required
def armor_add_to_char(character_id):
    char = tblCharacters.query.get_or_404(character_id)
    if not current_user.is_dm() and char.user_id != current_user.user_id:
        return jsonify({'ok': False}), 403
    data = request.get_json()
    entry = tblCharacterArmor(
        character_id    = character_id,
        armor_lib_id    = data.get('armor_lib_id') or None,
        armor_name      = data.get('armor_name', '').strip(),
        armor_category  = data.get('armor_category', ''),
        armor_class_base = int(data.get('armor_class_base', 0) or 0),
        dex_bonus       = int(data.get('dex_bonus', 0) or 0),
        max_dex_bonus   = data.get('max_dex_bonus'),   # may be None
        ac_bonus        = int(data.get('ac_bonus', 0) or 0),
        equipped        = int(data.get('equipped', 0) or 0),
        notes           = data.get('notes', '').strip(),
        order_by        = len(char.armor),
    )
    db.session.add(entry)
    db.session.commit()
    return jsonify({'ok': True, 'char_armor_id': entry.char_armor_id})


@ttrpg.route('/char-armor/<int:char_armor_id>', methods=['POST', 'DELETE'])
@login_required
def armor_update(char_armor_id):
    entry = tblCharacterArmor.query.get_or_404(char_armor_id)
    char  = entry.character
    if not current_user.is_dm() and char.user_id != current_user.user_id:
        return jsonify({'ok': False}), 403
    if request.method == 'DELETE':
        db.session.delete(entry)
        db.session.commit()
        return jsonify({'ok': True})
    data = request.get_json()
    if 'equipped' in data:
        entry.equipped = int(data['equipped'])
    if 'ac_bonus' in data:
        entry.ac_bonus = int(data.get('ac_bonus') or 0)
    if 'notes' in data:
        entry.notes = data['notes'].strip()
    db.session.commit()
    return jsonify({'ok': True})


# ── Character Weapons CRUD (AJAX) ──────────────────────────────────────────────

@ttrpg.route('/character/<int:character_id>/weapons', methods=['POST'])
@login_required
def weapon_add_to_char(character_id):
    char = tblCharacters.query.get_or_404(character_id)
    if not current_user.is_dm() and char.user_id != current_user.user_id:
        return jsonify({'ok': False}), 403
    data = request.get_json()
    entry = tblCharacterWeapons(
        character_id           = character_id,
        weapon_lib_id          = data.get('weapon_lib_id') or None,
        weapon_name            = data.get('weapon_name', '').strip(),
        weapon_category        = data.get('weapon_category', ''),
        weapon_range           = data.get('weapon_range', ''),
        damage_dice            = data.get('damage_dice', ''),
        damage_type            = data.get('damage_type', ''),
        two_handed_damage_dice = data.get('two_handed_damage_dice', ''),
        two_handed_damage_type = data.get('two_handed_damage_type', ''),
        range_normal           = int(data.get('range_normal', 0) or 0),
        range_long             = int(data.get('range_long', 0) or 0),
        attack_bonus           = int(data.get('attack_bonus', 0) or 0),
        damage_bonus           = int(data.get('damage_bonus', 0) or 0),
        properties             = data.get('properties', ''),
        equipped               = int(data.get('equipped', 0) or 0),
        notes                  = data.get('notes', '').strip(),
        order_by               = len(char.weapons),
    )
    db.session.add(entry)
    db.session.commit()
    return jsonify({'ok': True, 'char_weapon_id': entry.char_weapon_id})


@ttrpg.route('/char-weapon/<int:char_weapon_id>', methods=['POST', 'DELETE'])
@login_required
def weapon_char_update(char_weapon_id):
    entry = tblCharacterWeapons.query.get_or_404(char_weapon_id)
    char  = entry.character
    if not current_user.is_dm() and char.user_id != current_user.user_id:
        return jsonify({'ok': False}), 403
    if request.method == 'DELETE':
        db.session.delete(entry)
        db.session.commit()
        return jsonify({'ok': True})
    data = request.get_json()
    if 'equipped'      in data: entry.equipped      = int(data['equipped'])
    if 'attack_bonus'  in data: entry.attack_bonus  = int(data.get('attack_bonus')  or 0)
    if 'damage_bonus'  in data: entry.damage_bonus  = int(data.get('damage_bonus')  or 0)
    if 'notes'         in data: entry.notes         = data['notes'].strip()
    db.session.commit()
    return jsonify({'ok': True})


# ── Character Spells CRUD (AJAX) ───────────────────────────────────────────────

@ttrpg.route('/character/<int:character_id>/spells', methods=['POST'])
@login_required
def spell_add_to_char(character_id):
    char = tblCharacters.query.get_or_404(character_id)
    if not current_user.is_dm() and char.user_id != current_user.user_id:
        return jsonify({'ok': False}), 403
    data = request.get_json()
    spell_name = data.get('spell_name', '').strip()
    if not spell_name:
        return jsonify({'ok': False, 'error': 'Spell name is required'}), 400
    entry = tblCharacterSpells(
        character_id = character_id,
        spell_lib_id = data.get('spell_lib_id') or None,
        spell_name   = spell_name,
        spell_level  = int(data.get('spell_level', 0) or 0),
        school       = data.get('school', '').strip(),
        prepared     = int(data.get('prepared', 0) or 0),
        notes        = data.get('notes', '').strip(),
        order_by     = len(char.spells),
    )
    db.session.add(entry)
    db.session.commit()
    return jsonify({'ok': True, 'char_spell_id': entry.char_spell_id})


@ttrpg.route('/char-spell/<int:char_spell_id>', methods=['POST', 'DELETE'])
@login_required
def spell_char_update(char_spell_id):
    entry = tblCharacterSpells.query.get_or_404(char_spell_id)
    char  = entry.character
    if not current_user.is_dm() and char.user_id != current_user.user_id:
        return jsonify({'ok': False}), 403
    if request.method == 'DELETE':
        db.session.delete(entry)
        db.session.commit()
        return jsonify({'ok': True})
    data = request.get_json()
    if 'prepared' in data: entry.prepared = int(data['prepared'])
    if 'notes'    in data: entry.notes    = data['notes'].strip()
    db.session.commit()
    return jsonify({'ok': True})


# ── Dice Roller ───────────────────────────────────────────────────────────────

@ttrpg.route('/dice/roll', methods=['POST'])
@login_required
def dice_roll():
    import random, json as _json
    data      = request.get_json()
    char_id   = data.get('character_id')
    char_name = data.get('char_name', 'Unknown')[:60]
    count     = max(1, min(20, int(data.get('count', 1) or 1)))
    sides     = int(data.get('sides', 20))
    modifier  = max(-99, min(99, int(data.get('modifier', 0) or 0)))
    label     = (data.get('label') or '').strip()[:80]
    adv_mode  = data.get('adv_mode', 'normal')

    if sides not in (2, 4, 6, 8, 10, 12, 20, 100):
        sides = 20

    if adv_mode in ('advantage', 'disadvantage'):
        num  = max(2, count)
        dice = [random.randint(1, sides) for _ in range(num)]
        kept = max(dice) if adv_mode == 'advantage' else min(dice)
        total = kept + modifier
    else:
        adv_mode = 'normal'
        num  = count
        dice = [random.randint(1, sides) for _ in range(count)]
        total = sum(dice) + modifier

    expr = f'{num}d{sides}'
    if modifier > 0:  expr += f'+{modifier}'
    elif modifier < 0: expr += str(modifier)

    roll = tblDiceRolls(
        character_id = char_id,
        char_name    = char_name,
        expression   = expr,
        label        = label,
        dice_json    = _json.dumps(dice),
        modifier     = modifier,
        total        = total,
        adv_mode     = adv_mode,
        rolled_at    = _now(),
    )
    db.session.add(roll)
    db.session.flush()

    # Keep only the 50 most recent rolls
    old = db.session.query(tblDiceRolls.roll_id).order_by(
        tblDiceRolls.roll_id.desc()).offset(50).all()
    if old:
        tblDiceRolls.query.filter(
            tblDiceRolls.roll_id.in_([r[0] for r in old])
        ).delete(synchronize_session=False)
    db.session.commit()

    try:
        import relay_broadcaster
        relay_broadcaster.broadcast_roll(
            char_name, expr, label, dice, modifier, total, adv_mode,
        )
    except Exception:
        pass

    return jsonify({
        'ok': True, 'roll_id': roll.roll_id,
        'char_name': char_name, 'expression': expr, 'label': label,
        'dice': dice, 'modifier': modifier, 'total': total,
        'adv_mode': adv_mode, 'rolled_at': roll.rolled_at,
    })


@ttrpg.route('/dice/feed')
@login_required
def dice_feed():
    import json as _json
    since = request.args.get('since', 0, type=int)
    q = tblDiceRolls.query
    if since:
        q = q.filter(tblDiceRolls.roll_id > since)
    # Order by actual roll TIME, then break within-second ties by the relay's own
    # roll id (its true order) for relay rolls, falling back to local roll_id for
    # local rolls. Insertion order (roll_id) alone is wrong: a relay burst arrives
    # newest-first, so local inserts it reversed and roll_id anti-correlates with
    # the real order.
    rolls = (q.order_by(
                tblDiceRolls.rolled_at.desc(),
                tblDiceRolls.relay_roll_id.is_(None),   # relay rolls (non-null) first within a tie
                tblDiceRolls.relay_roll_id.desc(),      # newest relay roll first
                tblDiceRolls.roll_id.desc(),            # local rolls: insertion order
             ).limit(50).all())
    return jsonify([{
        'roll_id':    r.roll_id,
        'char_name':  r.char_name,
        'expression': r.expression,
        'label':      r.label,
        'dice':       _json.loads(r.dice_json or '[]'),
        'modifier':   r.modifier,
        'total':      r.total,
        'adv_mode':   r.adv_mode,
        'rolled_at':  r.rolled_at,
    } for r in rolls])


# ── Sessions ───────────────────────────────────────────────────────────────────

@ttrpg.route('/sessions')
@login_required
@dm_required
def sessions_list():
    sessions   = tblSessions.query.order_by(tblSessions.created_at.desc()).all()
    campaigns  = tblcampaigns.query.order_by(tblcampaigns.campaign_name).all()
    characters = tblCharacters.query.filter_by(active=1).order_by(tblCharacters.name).all()
    return render_template('ttrpg/sessions.html',
                           sessions=sessions,
                           campaigns=campaigns,
                           characters=characters)


@ttrpg.route('/sessions/new', methods=['GET', 'POST'])
@login_required
@dm_required
def session_new():
    campaigns  = tblcampaigns.query.order_by(tblcampaigns.campaign_name).all()
    characters = tblCharacters.query.filter_by(active=1).order_by(tblCharacters.name).all()
    error = None

    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        if not title:
            error = 'Session title is required.'
        else:
            campaign_id = request.form.get('campaign_id') or None
            if campaign_id:
                campaign_id = int(campaign_id)

            sess = tblSessions(
                title          = title,
                session_number = int(request.form.get('session_number', 1) or 1),
                campaign_id    = campaign_id,
                status         = 'planning',
                session_date   = request.form.get('session_date', ''),
                created_at     = _now(),
            )
            db.session.add(sess)
            db.session.flush()

            # Add selected characters to party
            char_ids = request.form.getlist('character_ids')
            for cid in char_ids:
                sp = tblSessionParty(
                    session_id   = sess.session_id,
                    character_id = int(cid),
                    is_active    = 1,
                    joined_at    = _now(),
                )
                db.session.add(sp)

            db.session.commit()
            return redirect(url_for('ttrpg.session_detail', session_id=sess.session_id))

    return render_template('ttrpg/session_new.html',
                           campaigns=campaigns,
                           characters=characters,
                           error=error,
                           today=datetime.now().strftime('%Y-%m-%d'))


@ttrpg.route('/sessions/<int:session_id>')
@login_required
@dm_required
def session_detail(session_id):
    sess = tblSessions.query.get_or_404(session_id)
    campaigns  = tblcampaigns.query.order_by(tblcampaigns.campaign_name).all()
    all_chars  = tblCharacters.query.filter_by(active=1).order_by(tblCharacters.name).all()
    party_ids  = {sp.character_id for sp in sess.party}
    campaign_scenes = []
    if sess.campaign_id:
        campaign_scenes = (tblscenes.query
                           .filter_by(campaign_id=sess.campaign_id, active=1)
                           .order_by(tblscenes.orderBy)
                           .all())
    try:
        from extensions import currentvolume
        current_vol = currentvolume()
    except Exception:
        current_vol = 50
    return render_template('ttrpg/session_detail.html',
                           sess=sess,
                           campaigns=campaigns,
                           all_chars=all_chars,
                           party_ids=party_ids,
                           conditions=condition_texts(),
                           campaign_scenes=campaign_scenes,
                           current_vol=current_vol)


@ttrpg.route('/sessions/<int:session_id>/status', methods=['POST'])
@login_required
@dm_required
def session_status(session_id):
    sess = tblSessions.query.get_or_404(session_id)
    new_status = request.form.get('status')
    if new_status in ('planning', 'active', 'ended'):
        # Only one session active at a time
        if new_status == 'active':
            tblSessions.query.filter_by(status='active').update({'status': 'ended'})
        sess.status = new_status
        db.session.commit()
        # The relay mirrors the ACTIVE session's party. Re-push it on
        # activation (authoritative replace) so players never see the
        # previous session's characters on their sheets.
        if new_status == 'active':
            relay_broadcaster.push_all_characters()
            relay_broadcaster.push_session_users()
    return redirect(url_for('ttrpg.session_detail', session_id=session_id))


@ttrpg.route('/sessions/<int:session_id>/notes', methods=['POST'])
@login_required
@dm_required
def session_notes_save(session_id):
    sess = tblSessions.query.get_or_404(session_id)
    sess.dm_notes = request.get_json().get('notes', '')
    db.session.commit()
    return jsonify({'ok': True})


@ttrpg.route('/sessions/<int:session_id>/edit', methods=['POST'])
@login_required
@dm_required
def session_edit(session_id):
    sess = tblSessions.query.get_or_404(session_id)
    data = request.get_json()
    if 'title' in data:
        title = data['title'].strip()
        if title:
            sess.title = title
    if 'session_number' in data:
        try:
            sess.session_number = int(data['session_number'])
        except (ValueError, TypeError):
            pass
    if 'session_date' in data:
        sess.session_date = data['session_date'] or ''
    if 'campaign_id' in data:
        cid = data['campaign_id']
        sess.campaign_id = int(cid) if cid else None
    db.session.commit()
    campaign_name = sess.campaign.campaign_name if sess.campaign else None
    return jsonify({'ok': True, 'campaign_name': campaign_name,
                    'title': sess.title, 'session_number': sess.session_number,
                    'session_date': sess.session_date})


@ttrpg.route('/sessions/<int:session_id>/party/add', methods=['POST'])
@login_required
@dm_required
def session_party_add(session_id):
    data = request.get_json()
    char_id = int(data.get('character_id'))
    existing = tblSessionParty.query.filter_by(
        session_id=session_id, character_id=char_id).first()
    if not existing:
        sp = tblSessionParty(
            session_id=session_id, character_id=char_id,
            is_active=1, joined_at=_now())
        db.session.add(sp)
        db.session.commit()
    relay_broadcaster.push_all_characters()
    return jsonify({'ok': True})


@ttrpg.route('/sessions/<int:session_id>/party/<int:char_id>/remove', methods=['POST'])
@login_required
@dm_required
def session_party_remove(session_id, char_id):
    sp = tblSessionParty.query.filter_by(
        session_id=session_id, character_id=char_id).first_or_404()
    char_name = sp.character.name if sp.character else None
    db.session.delete(sp)
    db.session.commit()
    relay_broadcaster.push_all_characters()
    # Drop it from the relay too — push_all only upserts, so without this the
    # departed character lingered until the session was recreated.
    if char_name:
        relay_broadcaster.remove_character(char_name)
    return jsonify({'ok': True})


@ttrpg.route('/sessions/<int:session_id>/delete', methods=['POST'])
@login_required
@dm_required
def session_delete(session_id):
    from models.ttrpg import tblBattleMaps as _tblBattleMaps, tblBattleMapTokens as _tblBattleMapTokens
    sess = tblSessions.query.get_or_404(session_id)
    title = sess.title
    tblSessionParty.query.filter_by(session_id=session_id).delete()
    _tblSessionMonsters.query.filter_by(session_id=session_id).delete()
    map_ids = [m.map_id for m in _tblBattleMaps.query.filter_by(session_id=session_id).all()]
    if map_ids:
        _tblBattleMapTokens.query.filter(
            _tblBattleMapTokens.map_id.in_(map_ids)
        ).delete(synchronize_session=False)
    _tblBattleMaps.query.filter_by(session_id=session_id).delete()
    db.session.delete(sess)
    db.session.commit()
    flash(f'Session "{title}" deleted.')
    return redirect(url_for('ttrpg.sessions_list'))

