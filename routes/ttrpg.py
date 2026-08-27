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
                           tblSessions, tblSessionParty, tblSessionNotes,
                           tblRacesLibrary, tblClassesLibrary, tblDiceRolls,
                           tblFeaturesLibrary, tblClassLevelsLibrary)
from models.campaigns import tblcampaigns
from models.scenes import tblscenes
from models.ttrpg import tblSessionMonsters as _tblSessionMonsters
from routes.auth import dm_required
from routes.monsters import condition_texts
import relay_broadcaster
import dice_systems


def active_game_info():
    """Game-system info for the dice rollers: the ACTIVE session's choice,
    or the D&D 5e default when no session is live."""
    return tblSessions.active_game_info()


def _game_fields_from(src):
    """(game_system, system_settings_json) from a form/JSON dict; unknown
    system ids fall back to the default."""
    import json as _json
    sys_id = (src.get('game_system') or dice_systems.DEFAULT_SYSTEM).strip()
    if sys_id not in dice_systems.SYSTEMS:
        sys_id = dice_systems.DEFAULT_SYSTEM
    raw = {}
    if src.get('floor') not in (None, ''):
        raw['floor'] = src.get('floor')
    return sys_id, _json.dumps(dice_systems.normalize_settings(sys_id, raw))


def _dcc_fields_from(src, base=None):
    return dice_systems.dcc_merge_fields(src, base)


def _dcc_pairing_warning(char):
    """Text if the sheet pairs an Earth Class with an Alien Race, else ''."""
    if char is None or not getattr(char, 'is_dcc', False) or not (char.race and char.char_class):
        return ''
    cls = tblClassesLibrary.query.filter(db.func.lower(tblClassesLibrary.name) == char.char_class.strip().lower(),
                                         tblClassesLibrary.game_system == 'dcc').first()
    race = tblRacesLibrary.query.filter(db.func.lower(tblRacesLibrary.name) == char.race.strip().lower(),
                                        tblRacesLibrary.game_system == 'dcc').first()
    if cls and race and 'Earth Class' in (cls.description or '') and (race.description or '').startswith('Alien Race'):
        return f'{cls.name} is an Earth Class, but {race.name} is an Alien Race — Alien Races cannot take Earth Classes (p.128).'
    return ''


def _sheet_context(char):
    """Template context shared by the sheet pages: system vocabulary."""
    return {
        'dcc_pairing_warning': _dcc_pairing_warning(char),
        'game': active_game_info(),
        'game_systems': dice_systems.SYSTEMS,
        'dcc': char.dcc() if char is not None else dice_systems.dcc_defaults(),
        'dcc_debuffs': dice_systems.DCC_DEBUFFS,
        'dcc_stat_names': dice_systems.DCC_STAT_NAMES,
        'dcc_skill_categories': dice_systems.DCC_SKILL_CATEGORIES,
        'dcc_sizes': dice_systems.DCC_SIZES,
    }


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


def _drop_portrait(char):
    """Remove a character's current portrait FILE before replacing it —
    unless it is a shared reference (another record's file) or another
    record still points at it (see shared_assets)."""
    import shared_assets
    from extensions import database
    name = char.portrait_path
    if not name or shared_assets.is_ref(name):
        return
    if shared_assets.referenced_elsewhere(database, 'portraits', name,
                                          exclude=('tblCharacters', 'character_id', char.character_id)):
        return
    old = os.path.join(current_app.root_path, PORTRAIT_FOLDER, name)
    if os.path.exists(old):
        os.remove(old)


def _portrait_ref_from_form():
    """A picked existing picture (portrait_ref) — validated, else ''."""
    import shared_assets
    from extensions import database
    ref = (request.form.get('portrait_ref') or '').strip()
    if ref and shared_assets.valid_ref(current_app.root_path, database, 'portraits', ref, kinds=('image',)):
        return ref
    return ''


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

    sessions = tblSessions.query.order_by(tblSessions.created_at.desc()).all()
    active_session = tblSessions.query.filter_by(status='active').first()

    # Session -> its party's character ids (comma-wrapped id strings for the
    # client-side filter dropdown, same shape as the dashboard's campaign filter).
    sess_chars = {}
    for sid, chid in (db.session.query(tblSessionParty.session_id,
                                       tblSessionParty.character_id)
                      .distinct().all()):
        sess_chars.setdefault(sid, set()).add(chid)
    session_char_ids = {sid: ',' + ','.join(str(i) for i in sorted(ids)) + ','
                        for sid, ids in sess_chars.items()}

    return render_template('ttrpg/characters.html',
                           characters=all_chars,
                           sessions=sessions,
                           session_char_ids=session_char_ids,
                           active_session=active_session)


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

    # Campaign scoping: while a session is live, default to the characters in
    # ITS party — a player's roster spans campaigns, and their sci-fi captain
    # shouldn't sit next to tonight's dungeon crawlers. "?all=1" shows the
    # full roster (that's also where brand-new characters appear).
    hidden_count = 0
    show_all = request.args.get('all') == '1'
    campaign_name = ''
    if active_session and not show_all:
        party_ids = {sp.character_id for sp in active_session.party}
        in_session = [c for c in chars if c.character_id in party_ids]
        hidden_count = len(chars) - len(in_session)
        chars = in_session
        if active_session.campaign_id:
            camp = db.session.get(tblcampaigns, active_session.campaign_id)
            campaign_name = camp.campaign_name if camp else ''

    from sql import appsettingGet
    return render_template('ttrpg/my_characters.html', characters=chars,
                           active_map=active_map, hidden_count=hidden_count,
                           show_all=show_all, campaign_name=campaign_name,
                           obs_enabled=appsettingGet('obs_enabled', '0') == '1')


# ── Character create ───────────────────────────────────────────────────────────

@ttrpg.route('/character/random')
@login_required
def character_random():
    """Roll a complete random character (level, stats, name, traits) as JSON
    for the create-character form to fill in."""
    if request.args.get('system') == 'dcc':
        # Dungeon Crawler Carl crawler (Chapter 3): First Floor = fresh from the
        # collapse; Third Floor = Level 10 with a Race and Class from the library.
        import dcc_randgen
        floor = 'third' if request.args.get('floor') == 'third' else 'first'
        races = tblRacesLibrary.query.filter_by(game_system='dcc').all()
        classes = tblClassesLibrary.query.filter_by(game_system='dcc').all()
        return jsonify(dcc_randgen.generate_crawler(floor, races=races, classes=classes))
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
            # Game system: the form's choice, else whatever the live session runs.
            gs = (request.form.get('game_system') or active_game_info()['id']).strip()
            char.game_system = gs if gs in dice_systems.SYSTEMS else dice_systems.DEFAULT_SYSTEM
            if char.is_dcc:
                import json as _json
                char.dcc_json = _json.dumps(_dcc_fields_from(request.form))
                # Health Bar: 10 slots, all full. hp_* count SLOTS under DCC so
                # tokens, the relay and HP bars keep working unchanged.
                char.hp_max = dice_systems.DCC_HB_SLOTS
                char.hp_current = dice_systems.DCC_HB_SLOTS
            db.session.add(char)
            db.session.flush()  # get character_id before portrait save
            if char.is_dcc:
                db.session.add(tblCharacterResources(
                    character_id=char.character_id, resource_name='Mana',
                    current_val=char.mana_max(), max_val=char.mana_max(), order_by=0))
                # Skills / starting items / applied bonuses from the crawler randomizer
                import json as _json
                try:
                    r_skills = _json.loads(request.form.get('dcc_skills_json') or '[]')
                    r_items = _json.loads(request.form.get('dcc_items_json') or '[]')
                    r_applied = _json.loads(request.form.get('dcc_applied_json') or '[]')
                except ValueError:
                    r_skills, r_items, r_applied = [], [], []
                for i, sk in enumerate(r_skills[:40]):
                    if not isinstance(sk, dict) or not str(sk.get('name', '')).strip():
                        continue
                    db.session.add(tblCharacterSkills(
                        character_id=char.character_id, skill_name=str(sk['name'])[:60],
                        bonus=max(0, min(20, int(sk.get('rank', 1) or 1))), proficient=1,
                        category=str(sk.get('category', ''))[:20], stat=str(sk.get('stat', ''))[:5],
                        order_by=i))
                for i, it in enumerate(r_items[:30]):
                    if not str(it).strip():
                        continue
                    db.session.add(tblCharacterInventory(
                        character_id=char.character_id, item_name=str(it)[:120], quantity=1,
                        weight='', notes='', equipped=0, order_by=i))
                if r_applied:
                    bag = char.dcc()
                    bag['applied'] = [str(a)[:80] for a in r_applied if isinstance(a, str)][:4]
                    char.dcc_json = _json.dumps(bag)

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

            # Portrait upload — or a picked existing picture (by reference)
            portrait = request.files.get('portrait')
            if portrait and portrait.filename and _allowed_file(portrait.filename):
                from routes._util import save_upload_downscaled
                filename = save_upload_downscaled(
                    portrait, os.path.join(current_app.root_path, PORTRAIT_FOLDER))
                char.portrait_path = filename
            elif _portrait_ref_from_form():
                char.portrait_path = _portrait_ref_from_form()

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
                           **_sheet_context(None),
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

    ctx = _sheet_context(char)
    if ctx['game']['id'] != (char.game_system or 'dnd5e'):
        # The roller on a sheet follows the SHEET's system (see dice_roll).
        ctx['game'] = {'id': char.game_system or 'dnd5e',
                       'name': dice_systems.system(char.game_system)['name'], 'settings': {}}
    return render_template('ttrpg/character_sheet.html', char=char,
                           **ctx,
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
    elif field == 'game_system':
        char.game_system = value if value in dice_systems.SYSTEMS else dice_systems.DEFAULT_SYSTEM
        if char.is_dcc and char.hp_max != dice_systems.DCC_HB_SLOTS:
            char.hp_max = dice_systems.DCC_HB_SLOTS      # switch to a 10-slot Health Bar
            char.hp_current = dice_systems.DCC_HB_SLOTS
    elif field.startswith('dcc_'):
        import json as _json
        char.dcc_json = _json.dumps(_dcc_fields_from({field: value}, char.dcc_json))
    else:
        return jsonify({'ok': False, 'error': 'unknown field'}), 400

    if char.is_dcc:
        _sync_mana(char)
    db.session.commit()
    if field in ('hp_current', 'hp_max'):
        token_id = relay_broadcaster.find_token_id('player', char.character_id)
        if token_id:
            relay_broadcaster.broadcast_token_health(token_id, char.hp_current, char.hp_max)
    relay_broadcaster.push_character(char)
    return jsonify({'ok': True, 'hp_pct': char.hp_pct()})


def _sync_mana(char):
    """DCC: Max Mana tracks the Enhanced Intelligence score (1:1)."""
    for r in char.resources:
        if r.resource_name.strip().lower() == 'mana':
            if r.max_val != char.mana_max():
                r.max_val = char.mana_max()
                r.current_val = min(r.current_val, r.max_val)
            return


@ttrpg.route('/character/<int:character_id>/apply-library', methods=['POST'])
@login_required
def apply_library(character_id):
    """DCC: apply Race/Class bonuses from the library to the sheet (once each)."""
    from models.ttrpg import apply_library_bonuses
    char = tblCharacters.query.get_or_404(character_id)
    if not current_user.is_dm() and char.user_id != current_user.user_id:
        return jsonify({'ok': False, 'error': 'forbidden'}), 403
    kind = (request.get_json(silent=True) or {}).get('kind', 'race')
    if kind not in ('race', 'class'):
        return jsonify({'ok': False, 'msg': 'kind must be race or class'}), 400
    out = apply_library_bonuses(char, kind, db)
    if out['ok']:
        _sync_mana(char)
        db.session.commit()
        relay_broadcaster.push_character(char)
    return jsonify(out)


# ── HP delta (apply damage / healing by amount) ───────────────────────────────

@ttrpg.route('/character/<int:character_id>/hp-delta', methods=['POST'])
@login_required
def hp_delta(character_id):
    char = tblCharacters.query.get_or_404(character_id)
    if not current_user.is_dm() and char.user_id != current_user.user_id:
        return jsonify({'ok': False, 'error': 'forbidden'}), 403
    data = request.get_json()
    slots = None
    if char.is_dcc and data.get('damage') is not None:
        # Dungeon Crawler Carl: damage → Health Bar slots (DR first, then one
        # slot per full Con Mod; leftovers ignored — p.93).
        slots = dice_systems.dcc_damage_slots(data.get('damage'), char.dr_total(),
                                              char.hb_slot_value())
        delta = -slots
    else:
        delta = int(data.get('delta', 0))
    char.hp_current = max(0, min(char.hp_max, char.hp_current + delta))
    db.session.commit()
    token_id = relay_broadcaster.find_token_id('player', char.character_id)
    if token_id:
        relay_broadcaster.broadcast_token_health(token_id, char.hp_current, char.hp_max)
    relay_broadcaster.push_character(char)
    return jsonify({'ok': True, 'hp_current': char.hp_current, 'hp_pct': char.hp_pct(),
                    'slots_lost': slots})


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
            gs = request.form.get('game_system')
            if gs in dice_systems.SYSTEMS:
                char.game_system = gs
            if char.is_dcc:
                import json as _json
                char.dcc_json = _json.dumps(_dcc_fields_from(request.form, char.dcc_json))
                char.hp_max = dice_systems.DCC_HB_SLOTS
                char.hp_current = max(0, min(char.hp_max, char.hp_current))
                _sync_mana(char)

            portrait = request.files.get('portrait')
            if portrait and portrait.filename and _allowed_file(portrait.filename):
                _drop_portrait(char)
                from routes._util import save_upload_downscaled
                filename = save_upload_downscaled(
                    portrait, os.path.join(current_app.root_path, PORTRAIT_FOLDER))
                char.portrait_path = filename
            elif _portrait_ref_from_form():
                _drop_portrait(char)
                char.portrait_path = _portrait_ref_from_form()

            db.session.commit()
            return redirect(url_for('ttrpg.character_sheet', character_id=char.character_id))

    return render_template('ttrpg/character_edit.html', char=char, error=error,
                           **_sheet_context(char))


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
    if not (portrait and portrait.filename) and _portrait_ref_from_form():
        # "Choose existing" from the sheet: point at the shared file.
        _drop_portrait(char)
        char.portrait_path = _portrait_ref_from_form()
        db.session.commit()
    elif portrait and portrait.filename and _allowed_file(portrait.filename):
        _drop_portrait(char)
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
    _drop_portrait(char)
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
        category     = (data.get('category') or '')[:20],
        stat         = (data.get('stat') or '')[:5],
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
    if 'category' in data: s.category = (data.get('category') or '')[:20]
    if 'stat' in data:     s.stat = (data.get('stat') or '')[:5]
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
        hotlist      = int(data.get('hotlist', 0) or 0),
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
    if 'hotlist' in data:
        item.hotlist = int(data.get('hotlist') or 0)
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
    # Game-system context (dice_systems.py). The SYSTEM is always the active
    # session's — a stale page can't roll under other rules — while the
    # target number / roll type come from the roller's controls.
    game       = active_game_info()
    if char_id:
        # A sheet rolls under the CHARACTER's rules: a 5e sheet in a DCC session
        # (or vice versa) shouldn't be judged by the other game's table.
        _ch = db.session.get(tblCharacters, int(char_id)) if str(char_id).isdigit() else None
        if _ch is not None and (_ch.game_system or 'dnd5e') != game['id']:
            game = {'id': _ch.game_system or 'dnd5e',
                    'name': dice_systems.system(_ch.game_system)['name'], 'settings': {}}
    roll_type  = (data.get('roll_type') or 'other')[:20]
    difficulty = data.get('difficulty')
    rank       = data.get('rank')
    try:
        floor = int(data.get('floor', game['settings'].get('floor', 0)) or 0)
    except (TypeError, ValueError):
        floor = int(game['settings'].get('floor', 0) or 0)

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

    natural = kept if adv_mode != 'normal' else (dice[0] if len(dice) == 1 else None)
    outcome = dice_systems.evaluate(game['id'], sides, natural, total, roll_type,
                                    difficulty, floor, rank)
    label = dice_systems.annotate_label(label, outcome, difficulty)[:120]

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
        'outcome': outcome, 'difficulty': difficulty, 'system': game['id'],
    })


@ttrpg.route('/dice/system')
@login_required
def dice_system():
    """Which game system the rollers should follow right now (the active
    session's), plus its per-session settings (e.g. the DCC Floor). Rollers
    poll this alongside the feed so a mid-session Floor change reaches every
    open page."""
    return jsonify(active_game_info())


def clear_roll_history():
    """Wipe the shared roll feed and the session roll log. Returns how many
    rows went.

    The watermark matters as much as the delete: without it the relay receiver
    would re-import the very rolls just cleared on its next sync, and the feed
    would refill by itself a few seconds later."""
    from datetime import datetime, timezone
    from models.tblRollLog import tblRollLog
    from sql import appsettingSet
    appsettingSet('relay_roll_cleared_at',
                  datetime.now(timezone.utc).isoformat())
    removed = tblDiceRolls.query.delete()
    removed += tblRollLog.query.delete()
    db.session.commit()
    return removed


@ttrpg.route('/dice/clear', methods=['POST'])
@login_required
@dm_required
def dice_clear():
    """Empty the roll feed for everyone.

    Server-side on purpose: the feed is shared, so clearing it in this browser
    alone would leave the same rolls sitting on every player's map and on the
    stream overlay, and the next poll would put them back here too."""
    return jsonify({'ok': True, 'removed': clear_roll_history()})


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

            game_system, system_settings = _game_fields_from(request.form)
            sess = tblSessions(
                title          = title,
                session_number = int(request.form.get('session_number', 1) or 1),
                campaign_id    = campaign_id,
                status         = 'planning',
                session_date   = request.form.get('session_date', ''),
                created_at     = _now(),
                game_system    = game_system,
                system_settings= system_settings,
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
                           game_systems=dice_systems.SYSTEMS,
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
    # Same OBS markers as the battle map's scene list — the buttons are the
    # same buttons, and a marker on one page but not the other reads as a bug.
    obs_scene_links, obs_links_live = {}, False
    if current_user.is_dm():
        from routes.obs import scene_link_map, scene_links_live
        obs_scene_links = scene_link_map()
        obs_links_live = scene_links_live()
    return render_template('ttrpg/session_detail.html',
                           sess=sess,
                           campaigns=campaigns,
                           game_systems=dice_systems.SYSTEMS,
                           game=sess.game_info(),
                           all_chars=all_chars,
                           party_ids=party_ids,
                           conditions=condition_texts(),
                           campaign_scenes=campaign_scenes,
                           obs_scene_links=obs_scene_links,
                           obs_links_live=obs_links_live,
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
            relay_broadcaster.push_character_feeds()
    return redirect(url_for('ttrpg.session_detail', session_id=session_id))


# ── Session notes (many per session; mirrors the battlemap notes CRUD) ───────
# tblSessions.dm_notes is legacy — its content was migrated into these rows
# (0006_session_notes) and nothing writes it anymore.

@ttrpg.route('/sessions/<int:session_id>/notes/list')
@login_required
@dm_required
def session_notes_list(session_id):
    tblSessions.query.get_or_404(session_id)
    notes = (tblSessionNotes.query.filter_by(session_id=session_id)
             .order_by(tblSessionNotes.sort_order,
                       tblSessionNotes.note_id.desc())
             .all())
    return jsonify({'ok': True, 'notes': [{
        'note_id':    n.note_id,
        'title':      n.title,
        'body':       n.body,
        'updated_at': n.updated_at,
    } for n in notes]})


@ttrpg.route('/sessions/<int:session_id>/notes/add', methods=['POST'])
@login_required
@dm_required
def session_notes_add(session_id):
    tblSessions.query.get_or_404(session_id)
    data = request.get_json() or {}
    # New notes land at the top; reorder re-normalizes to 0..n-1, so drifting
    # negative is harmless.
    min_sort = (db.session.query(db.func.min(tblSessionNotes.sort_order))
                .filter_by(session_id=session_id).scalar())
    n = tblSessionNotes(
        session_id = session_id,
        title      = (data.get('title') or '').strip()[:120],
        body       = data.get('body') or '',
        sort_order = (min_sort - 1) if min_sort is not None else 0,
        created_at = _now(),
        updated_at = _now(),
    )
    db.session.add(n)
    db.session.commit()
    return jsonify({'ok': True, 'note_id': n.note_id})


@ttrpg.route('/sessions/<int:session_id>/notes/<int:note_id>/update', methods=['POST'])
@login_required
@dm_required
def session_notes_update(session_id, note_id):
    n = tblSessionNotes.query.get_or_404(note_id)
    if n.session_id != session_id:
        return jsonify({'ok': False}), 403
    data = request.get_json() or {}
    if 'title' in data:
        n.title = (data.get('title') or '').strip()[:120]
    if 'body' in data:
        n.body = data.get('body') or ''
    n.updated_at = _now()
    db.session.commit()
    return jsonify({'ok': True})


@ttrpg.route('/sessions/<int:session_id>/notes/<int:note_id>/reorder', methods=['POST'])
@login_required
@dm_required
def session_notes_reorder(session_id, note_id):
    """Move a note one step up/down (normalize-then-swap, as map_reorder)."""
    n = tblSessionNotes.query.get_or_404(note_id)
    if n.session_id != session_id:
        return jsonify({'ok': False}), 403
    direction = (request.get_json() or {}).get('direction', '')
    notes = (tblSessionNotes.query.filter_by(session_id=session_id)
             .order_by(tblSessionNotes.sort_order,
                       tblSessionNotes.note_id.desc())
             .all())
    for i, x in enumerate(notes):
        x.sort_order = i
    idx = next((i for i, x in enumerate(notes) if x.note_id == note_id), None)
    if idx is not None:
        swap = idx - 1 if direction == 'up' else idx + 1 if direction == 'down' else None
        if swap is not None and 0 <= swap < len(notes):
            notes[idx].sort_order, notes[swap].sort_order = \
                notes[swap].sort_order, notes[idx].sort_order
    db.session.commit()
    return jsonify({'ok': True})


@ttrpg.route('/sessions/<int:session_id>/notes/<int:note_id>/delete', methods=['POST'])
@login_required
@dm_required
def session_notes_delete(session_id, note_id):
    n = tblSessionNotes.query.get_or_404(note_id)
    if n.session_id != session_id:
        return jsonify({'ok': False}), 403
    db.session.delete(n)
    db.session.commit()
    return jsonify({'ok': True})


@ttrpg.route('/sessions/<int:session_id>/mapnotes/list')
@login_required
@dm_required
def session_mapnotes_list(session_id):
    """All battle-map notes of this session, grouped by map (DM display order).

    Feeds the session page's Map Notes tab; the CRUD itself reuses the
    per-map /ttrpg/battlemap/<map_id>/notes/* endpoints."""
    from models.ttrpg import tblBattleMaps, tblBattleMapNotes
    tblSessions.query.get_or_404(session_id)
    maps = (tblBattleMaps.query.filter_by(session_id=session_id)
            .order_by(tblBattleMaps.sort_order, tblBattleMaps.map_id)
            .all())
    out = []
    for m in maps:
        notes = (tblBattleMapNotes.query.filter_by(map_id=m.map_id)
                 .order_by(tblBattleMapNotes.sort_order,
                           tblBattleMapNotes.note_id.desc())
                 .all())
        out.append({'map_id': m.map_id, 'name': m.name, 'notes': [{
            'note_id':    n.note_id,
            'title':      n.title,
            'body':       n.body,
            'updated_at': n.updated_at,
        } for n in notes]})
    return jsonify({'ok': True, 'maps': out})


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
    if 'game_system' in data or 'floor' in data:
        src = {'game_system': data.get('game_system') or sess.game_system,
               'floor': data.get('floor', sess.game_info()['settings'].get('floor'))}
        sess.game_system, sess.system_settings = _game_fields_from(src)
    db.session.commit()
    if sess.status == 'active':
        relay_broadcaster.broadcast_game(sess)   # remote rollers follow the change
    campaign_name = sess.campaign.campaign_name if sess.campaign else None
    return jsonify({'ok': True, 'campaign_name': campaign_name,
                    'title': sess.title, 'session_number': sess.session_number,
                    'session_date': sess.session_date,
                    'game': sess.game_info()})


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

