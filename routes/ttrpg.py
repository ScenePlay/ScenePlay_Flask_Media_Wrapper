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
                           tblRacesLibrary, tblClassesLibrary, tblDiceRolls)
from models.campaigns import tblcampaigns
from models.scenes import tblscenes
from models.ttrpg import tblSessionMonsters as _tblSessionMonsters
from routes.auth import dm_required
from routes.monsters import CONDITIONS

ttrpg = Blueprint('ttrpg', __name__, url_prefix='/ttrpg')

PORTRAIT_FOLDER = os.path.join('static', 'uploads', 'portraits')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}


def _allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def _now():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


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
    return render_template('ttrpg/dashboard.html',
                           campaigns=campaigns,
                           sessions=sessions,
                           characters=characters,
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
                race       = request.form.get('race', '').strip(),
                level      = int(request.form.get('level', 1) or 1),
                background = request.form.get('background', '').strip(),
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

            # Portrait upload
            portrait = request.files.get('portrait')
            if portrait and portrait.filename and _allowed_file(portrait.filename):
                ext = portrait.filename.rsplit('.', 1)[1].lower()
                filename = f"{uuid.uuid4().hex}.{ext}"
                save_path = os.path.join(current_app.root_path, PORTRAIT_FOLDER, filename)
                portrait.save(save_path)
                char.portrait_path = filename

            db.session.commit()
            return redirect(url_for('ttrpg.character_sheet', character_id=char.character_id))

    return render_template('ttrpg/character_new.html', error=error)


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
    return render_template('ttrpg/character_sheet.html', char=char,
                           all_players=all_players, conditions=CONDITIONS,
                           races_lib=races_lib, classes_lib=classes_lib,
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
    text_fields = {'name', 'char_class', 'race', 'background'}

    if field in int_fields:
        setattr(char, field, int(value or 0))
    elif field in text_fields:
        setattr(char, field, str(value or ''))
    else:
        return jsonify({'ok': False, 'error': 'unknown field'}), 400

    db.session.commit()
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
                ext = portrait.filename.rsplit('.', 1)[1].lower()
                filename = f"{uuid.uuid4().hex}.{ext}"
                portrait.save(os.path.join(current_app.root_path, PORTRAIT_FOLDER, filename))
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
        user = tblUsers.query.get(new_user_id)
        if user:
            char.user_id = new_user_id
            db.session.commit()
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
        ext = portrait.filename.rsplit('.', 1)[1].lower()
        filename = f"{uuid.uuid4().hex}.{ext}"
        portrait.save(os.path.join(current_app.root_path, PORTRAIT_FOLDER, filename))
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
    filename = f"{uuid.uuid4().hex}.png"
    portrait.save(os.path.join(current_app.root_path, PORTRAIT_FOLDER, filename))
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
        dice = [random.randint(1, sides), random.randint(1, sides)]
        kept = max(dice) if adv_mode == 'advantage' else min(dice)
        total = kept + modifier
    else:
        adv_mode = 'normal'
        dice = [random.randint(1, sides) for _ in range(count)]
        total = sum(dice) + modifier

    expr = f'{count}d{sides}'
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
    rolls = q.order_by(tblDiceRolls.roll_id.desc()).limit(50).all()
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
    return render_template('ttrpg/session_detail.html',
                           sess=sess,
                           campaigns=campaigns,
                           all_chars=all_chars,
                           party_ids=party_ids,
                           conditions=CONDITIONS,
                           campaign_scenes=campaign_scenes)


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
    return jsonify({'ok': True})


@ttrpg.route('/sessions/<int:session_id>/party/<int:char_id>/remove', methods=['POST'])
@login_required
@dm_required
def session_party_remove(session_id, char_id):
    sp = tblSessionParty.query.filter_by(
        session_id=session_id, character_id=char_id).first_or_404()
    db.session.delete(sp)
    db.session.commit()
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

