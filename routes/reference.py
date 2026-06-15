import os
import uuid
import threading
import requests
from datetime import datetime
from flask import Blueprint, render_template, redirect, url_for, request, flash, jsonify, current_app
from flask_login import login_required
from werkzeug.utils import secure_filename
from extensions import db
from models.ttrpg import tblFeatsLibrary, tblWeaponsLibrary, tblArmorLibrary, tblDnDAPIConfig, tblSpellsLibrary, tblSkillsLibrary, tblRacesLibrary, tblEquipmentLibrary, tblClassesLibrary
from routes.auth import dm_required

WEAPON_IMG_FOLDER = os.path.join('static', 'uploads', 'weapons')
ALLOWED_IMG_EXTS  = {'png', 'jpg', 'jpeg', 'gif', 'webp'}


ARMOR_IMG_FOLDER = os.path.join('static', 'uploads', 'armor')


def _save_upload(file_field, subfolder):
    """Save an uploaded image to static/uploads/<subfolder>/; return URL or None."""
    f = request.files.get(file_field)
    if not f or not f.filename:
        return None
    ext = f.filename.rsplit('.', 1)[-1].lower()
    if ext not in ALLOWED_IMG_EXTS:
        return None
    filename = f'{uuid.uuid4().hex}.{ext}'
    folder = os.path.join(current_app.root_path, 'static', 'uploads', subfolder)
    os.makedirs(folder, exist_ok=True)
    f.save(os.path.join(folder, filename))
    return url_for('static', filename=f'uploads/{subfolder}/{filename}')


def _save_weapon_image(file_field):
    return _save_upload(file_field, 'weapons')


def _save_armor_image(file_field):
    return _save_upload(file_field, 'armor')

reference_bp = Blueprint('reference_bp', __name__, url_prefix='/ttrpg/reference')

_sync_states = {}   # {job_type: {total, done, added, skipped, errors, running, message}}

DEFAULT_API_BASE = 'https://www.dnd5eapi.co/api/2014'

API_OPTIONS = {
    'https://www.dnd5eapi.co/api/2014': {
        'label':    '2014 SRD',
        'monsters': '335',
        'feats':    '1',
        'weapons':  '~67',
        'note':     'Best monster coverage. Limited feats (PHB not open).',
    },
    'https://www.dnd5eapi.co/api/2024': {
        'label':    '2024 (PHB 2024)',
        'monsters': '3',
        'feats':    '17',
        'weapons':  '38',
        'note':     'More feats available. Monster library is very limited.',
    },
}


def _now():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def get_api_base():
    s = tblDnDAPIConfig.query.filter_by(key='dnd_api_base').first()
    return s.value if s else DEFAULT_API_BASE


def _api_version(api_base):
    return '2024' if '2024' in api_base else '2014'


# ── Feats sync ─────────────────────────────────────────────────────────────────

def sync_feats_from_api(state=None):
    api_base = get_api_base()
    version = _api_version(api_base)
    try:
        resp = requests.get(f'{api_base}/feats', timeout=15)
        resp.raise_for_status()
        feat_list = resp.json().get('results', [])
    except Exception as e:
        return 0, 0, str(e)

    if state is not None:
        state['total'] = len(feat_list)

    added = skipped = errors = 0
    for i, entry in enumerate(feat_list):
        try:
            index = entry['index']
            if tblFeatsLibrary.query.filter_by(api_index=index).first():
                skipped += 1
                continue
            try:
                detail = requests.get(f'{api_base}/feats/{index}', timeout=10)
                detail.raise_for_status()
                data = detail.json()

                if version == '2024':
                    description = data.get('description', '')
                    feat_type = data.get('type', '')
                    prerequisites = f'Type: {feat_type.replace("-", " ").title()}' if feat_type else ''
                else:
                    description = '\n'.join(data.get('desc', []))
                    prerequisites = ', '.join(
                        f"{p['ability_score']['name']} {p['minimum_score']}+"
                        for p in data.get('prerequisites', [])
                        if 'ability_score' in p
                    )

                feat = tblFeatsLibrary(
                    api_index=index,
                    name=data['name'],
                    prerequisites=prerequisites,
                    description=description,
                    source='srd',
                    created_at=_now(),
                )
                db.session.add(feat)
                db.session.commit()
                added += 1
            except Exception:
                errors += 1
        finally:
            if state is not None:
                state.update({'done': i + 1, 'added': added, 'skipped': skipped, 'errors': errors})
    return added, skipped, errors


# ── Weapons sync ───────────────────────────────────────────────────────────────

def sync_weapons_from_api(state=None):
    api_base = get_api_base()
    version = _api_version(api_base)
    cat_path = 'weapons' if version == '2024' else 'weapon'

    try:
        resp = requests.get(f'{api_base}/equipment-categories/{cat_path}', timeout=15)
        resp.raise_for_status()
        weapon_list = resp.json().get('equipment', [])
    except Exception as e:
        return 0, 0, str(e)

    if state is not None:
        state['total'] = len(weapon_list)

    added = skipped = errors = 0
    for i, entry in enumerate(weapon_list):
        _outcome = 'skip'
        try:
            index = entry['index']
            if tblWeaponsLibrary.query.filter_by(api_index=index).first():
                _outcome = 'skip'
            else:
                try:
                    detail = requests.get(f'{api_base}/equipment/{index}', timeout=10)

                    if detail.status_code == 404:
                        # Magic weapons live under /magic-items/ instead of /equipment/
                        magic = requests.get(f'{api_base}/magic-items/{index}', timeout=10)
                        if magic.status_code == 404:
                            _outcome = 'skip'
                        else:
                            magic.raise_for_status()
                            mdata = magic.json()
                            desc_lines = mdata.get('desc', [])
                            type_line  = desc_lines[0] if desc_lines else ''
                            full_desc  = '\n'.join(desc_lines[1:]) if len(desc_lines) > 1 else ''
                            raw_img    = mdata.get('image', '')
                            image_url  = ('https://www.dnd5eapi.co' + raw_img) if raw_img else ''
                            w = tblWeaponsLibrary(
                                api_index=index,
                                name=mdata['name'],
                                weapon_category='Magic',
                                weapon_range='',
                                damage_dice='',
                                damage_type='',
                                two_handed_damage_dice='',
                                two_handed_damage_type='',
                                range_normal=0,
                                range_long=0,
                                weight=0,
                                cost='',
                                properties=type_line,
                                mastery='',
                                notes=full_desc,
                                image_url=image_url,
                                source='srd-magic',
                                created_at=_now(),
                            )
                            db.session.add(w)
                            db.session.commit()
                            _outcome = 'add'
                    else:
                        detail.raise_for_status()
                        data = detail.json()

                        if not data.get('damage'):
                            _outcome = 'skip'
                        else:
                            dmg   = data['damage']
                            two_h = data.get('two_handed_damage') or {}
                            cost  = data.get('cost') or {}
                            rng   = data.get('range') or {}
                            throw_rng = data.get('throw_range') or {}

                            if version == '2024':
                                cats = [c['index'] for c in data.get('equipment_categories', [])]
                                weapon_category = ('Martial' if 'martial-weapons' in cats
                                                   else 'Simple' if 'simple-weapons' in cats else '')
                                weapon_range    = ('Ranged' if 'ranged-weapons' in cats
                                                   else 'Melee' if 'melee-weapons' in cats else '')
                                mastery = data.get('mastery', {}).get('name', '') if data.get('mastery') else ''
                            else:
                                weapon_category = data.get('weapon_category', '')
                                weapon_range    = data.get('weapon_range', '')
                                mastery = ''

                            if weapon_range == 'Ranged':
                                range_normal = rng.get('normal', 0)
                                range_long   = rng.get('long', 0)
                            elif throw_rng:
                                range_normal = throw_rng.get('normal', 0)
                                range_long   = throw_rng.get('long', 0)
                            else:
                                range_normal = range_long = 0

                            w = tblWeaponsLibrary(
                                api_index=index,
                                name=data['name'],
                                weapon_category=weapon_category,
                                weapon_range=weapon_range,
                                damage_dice=dmg.get('damage_dice', ''),
                                damage_type=dmg.get('damage_type', {}).get('name', ''),
                                two_handed_damage_dice=two_h.get('damage_dice', ''),
                                two_handed_damage_type=two_h.get('damage_type', {}).get('name', ''),
                                range_normal=range_normal,
                                range_long=range_long,
                                weight=data.get('weight', 0),
                                cost=f"{cost.get('quantity', '')} {cost.get('unit', '')}".strip(),
                                properties=', '.join(p['name'] for p in data.get('properties', [])),
                                mastery=mastery,
                                notes='',
                                image_url='',
                                source='srd',
                                created_at=_now(),
                            )
                            db.session.add(w)
                            db.session.commit()
                            _outcome = 'add'
                except Exception:
                    _outcome = 'error'
        except Exception:
            _outcome = 'error'
        finally:
            if _outcome == 'add':
                added += 1
            elif _outcome == 'skip':
                skipped += 1
            else:
                errors += 1
            if state is not None:
                state.update({'done': i + 1, 'added': added, 'skipped': skipped, 'errors': errors})
    return added, skipped, errors


# ── API Settings ───────────────────────────────────────────────────────────────

@reference_bp.route('/settings', methods=['GET', 'POST'])
@login_required
@dm_required
def api_settings():
    if request.method == 'POST':
        choice = request.form.get('api_choice', '').strip()
        custom = request.form.get('custom_url', '').strip()
        new_url = custom if choice == 'custom' else choice
        if not new_url:
            flash('API URL cannot be empty.')
            return redirect(url_for('reference_bp.api_settings'))

        setting = tblDnDAPIConfig.query.filter_by(key='dnd_api_base').first()
        if setting:
            setting.value = new_url
            setting.updated_at = _now()
        else:
            db.session.add(tblDnDAPIConfig(key='dnd_api_base', value=new_url, updated_at=_now()))
        db.session.commit()
        flash(f'API URL updated to: {new_url}')
        return redirect(url_for('reference_bp.api_settings'))

    current = get_api_base()
    return render_template('ttrpg/api_settings.html',
                           current=current,
                           api_options=API_OPTIONS,
                           default=DEFAULT_API_BASE)


@reference_bp.route('/settings/test')
@login_required
@dm_required
def api_test():
    api_base = request.args.get('url', get_api_base()).strip()
    try:
        resp = requests.get(api_base, timeout=8)
        resp.raise_for_status()
        keys = list(resp.json().keys())[:8]
        return jsonify({'ok': True, 'endpoints': keys})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)})


# ── Feats library ──────────────────────────────────────────────────────────────

@reference_bp.route('/feats')
@login_required
@dm_required
def feats_library():
    total = tblFeatsLibrary.query.count()
    q = request.args.get('q', '').strip()
    src = request.args.get('src', '').strip()
    feats = tblFeatsLibrary.query
    if q:
        feats = feats.filter(tblFeatsLibrary.name.ilike(f'%{q}%'))
    if src:
        feats = feats.filter(tblFeatsLibrary.source == src)
    feats = feats.order_by(tblFeatsLibrary.name).all()
    current_api = get_api_base()
    return render_template('ttrpg/feats_library.html',
                           feats=feats, total=total, q=q, src=src,
                           current_api=current_api,
                           api_options=API_OPTIONS)


@reference_bp.route('/feats/sync', methods=['POST'])
@login_required
@dm_required
def feats_sync():
    key = 'feats'
    if _sync_states.get(key, {}).get('running'):
        return jsonify({'error': 'Sync already in progress'}), 409
    state = {'total': 0, 'done': 0, 'added': 0, 'skipped': 0, 'errors': 0, 'running': True, 'message': ''}
    _sync_states[key] = state
    app = current_app._get_current_object()
    def _run():
        with app.app_context():
            added, skipped, errors = sync_feats_from_api(state=state)
            state.update({'running': False, 'message': f'{added} added, {skipped} skipped, {errors} errors.'})
    threading.Thread(target=_run, daemon=True).start()
    return jsonify({'job': key})


@reference_bp.route('/feats/add', methods=['POST'])
@login_required
@dm_required
def feat_add():
    name = request.form.get('name', '').strip()
    if not name:
        flash('Feat name is required.')
        return redirect(url_for('reference_bp.feats_library'))
    feat = tblFeatsLibrary(
        api_index=None,
        name=name,
        prerequisites=request.form.get('prerequisites', '').strip(),
        description=request.form.get('description', '').strip(),
        source='homebrew',
        created_at=_now(),
    )
    db.session.add(feat)
    db.session.commit()
    flash(f'Added custom feat "{name}".')
    return redirect(url_for('reference_bp.feats_library'))


@reference_bp.route('/feats/<int:feat_lib_id>/delete', methods=['POST'])
@login_required
@dm_required
def feat_delete(feat_lib_id):
    feat = tblFeatsLibrary.query.get_or_404(feat_lib_id)
    if feat.source != 'homebrew':
        flash('Only custom feats can be deleted.')
        return redirect(url_for('reference_bp.feats_library'))
    db.session.delete(feat)
    db.session.commit()
    flash(f'Deleted "{feat.name}".')
    return redirect(url_for('reference_bp.feats_library'))


@reference_bp.route('/feats/search')
@login_required
def feats_search():
    q = request.args.get('q', '').strip()
    feats = tblFeatsLibrary.query.filter(
        tblFeatsLibrary.name.ilike(f'%{q}%')
    ).order_by(tblFeatsLibrary.name).limit(500).all()
    return jsonify([{
        'feat_lib_id':   f.feat_lib_id,
        'name':          f.name,
        'prerequisites': f.prerequisites,
        'description':   f.description,
    } for f in feats])


# ── Weapons library ────────────────────────────────────────────────────────────

@reference_bp.route('/weapons/add', methods=['POST'])
@login_required
@dm_required
def weapon_add():
    name = request.form.get('name', '').strip()
    if not name:
        flash('Weapon name is required.')
        return redirect(url_for('reference_bp.weapons_library'))
    uploaded = _save_weapon_image('image_file')
    image_url = uploaded or request.form.get('image_url', '')
    w = tblWeaponsLibrary(
        name                   = name,
        weapon_category        = request.form.get('weapon_category', ''),
        weapon_range           = request.form.get('weapon_range', ''),
        damage_dice            = request.form.get('damage_dice', ''),
        damage_type            = request.form.get('damage_type', ''),
        two_handed_damage_dice = request.form.get('two_handed_damage_dice', ''),
        two_handed_damage_type = request.form.get('two_handed_damage_type', ''),
        range_normal           = int(request.form.get('range_normal') or 0),
        range_long             = int(request.form.get('range_long') or 0),
        cost                   = request.form.get('cost', ''),
        weight                 = float(request.form.get('weight') or 0),
        properties             = request.form.get('properties', ''),
        mastery                = request.form.get('mastery', ''),
        notes                  = request.form.get('notes', ''),
        image_url              = image_url,
        source                 = 'homebrew',
        created_at             = datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    )
    db.session.add(w)
    db.session.commit()
    flash(f'Added "{name}" to the weapons library.')
    return redirect(url_for('reference_bp.weapons_library'))


@reference_bp.route('/weapons/<int:weapon_lib_id>/edit', methods=['POST'])
@login_required
@dm_required
def weapon_edit(weapon_lib_id):
    w = tblWeaponsLibrary.query.get_or_404(weapon_lib_id)
    w.name                   = request.form.get('name', w.name).strip() or w.name
    w.weapon_category        = request.form.get('weapon_category', w.weapon_category)
    w.weapon_range           = request.form.get('weapon_range', w.weapon_range)
    w.damage_dice            = request.form.get('damage_dice', w.damage_dice)
    w.damage_type            = request.form.get('damage_type', w.damage_type)
    w.two_handed_damage_dice = request.form.get('two_handed_damage_dice', w.two_handed_damage_dice)
    w.two_handed_damage_type = request.form.get('two_handed_damage_type', w.two_handed_damage_type)
    w.range_normal           = int(request.form.get('range_normal') or 0)
    w.range_long             = int(request.form.get('range_long') or 0)
    w.cost                   = request.form.get('cost', w.cost)
    w.weight                 = float(request.form.get('weight') or 0)
    w.properties             = request.form.get('properties', w.properties)
    w.mastery                = request.form.get('mastery', w.mastery)
    w.notes                  = request.form.get('notes', w.notes)
    uploaded = _save_weapon_image('image_file')
    if uploaded:
        w.image_url = uploaded
    elif request.form.get('image_url', '').strip():
        w.image_url = request.form.get('image_url').strip()
    db.session.commit()
    flash(f'Updated "{w.name}".')
    return redirect(url_for('reference_bp.weapons_library'))


@reference_bp.route('/weapons/<int:weapon_lib_id>/delete', methods=['POST'])
@login_required
@dm_required
def weapon_delete(weapon_lib_id):
    w = tblWeaponsLibrary.query.get_or_404(weapon_lib_id)
    name = w.name
    db.session.delete(w)
    db.session.commit()
    flash(f'Deleted "{name}".')
    return redirect(url_for('reference_bp.weapons_library'))


@reference_bp.route('/weapons')
@login_required
@dm_required
def weapons_library():
    total = tblWeaponsLibrary.query.count()
    q = request.args.get('q', '').strip()
    cat = request.args.get('cat', '').strip()
    rng = request.args.get('rng', '').strip()
    src = request.args.get('src', '').strip()

    weapons = tblWeaponsLibrary.query
    if q:
        weapons = weapons.filter(tblWeaponsLibrary.name.ilike(f'%{q}%'))
    if cat:
        weapons = weapons.filter(tblWeaponsLibrary.weapon_category == cat)
    if rng:
        weapons = weapons.filter(tblWeaponsLibrary.weapon_range == rng)
    if src:
        weapons = weapons.filter(tblWeaponsLibrary.source == src)
    weapons = weapons.order_by(
        tblWeaponsLibrary.weapon_category,
        tblWeaponsLibrary.weapon_range,
        tblWeaponsLibrary.name
    ).all()
    current_api = get_api_base()
    return render_template('ttrpg/weapons_library.html',
                           weapons=weapons, total=total, q=q, cat=cat, rng=rng, src=src,
                           current_api=current_api,
                           api_options=API_OPTIONS)


@reference_bp.route('/weapons/sync', methods=['POST'])
@login_required
@dm_required
def weapons_sync():
    key = 'weapons'
    if _sync_states.get(key, {}).get('running'):
        return jsonify({'error': 'Sync already in progress'}), 409
    state = {'total': 0, 'done': 0, 'added': 0, 'skipped': 0, 'errors': 0, 'running': True, 'message': ''}
    _sync_states[key] = state
    app = current_app._get_current_object()
    def _run():
        with app.app_context():
            added, skipped, errors = sync_weapons_from_api(state=state)
            state.update({'running': False, 'message': f'{added} added, {skipped} skipped, {errors} errors.'})
    threading.Thread(target=_run, daemon=True).start()
    return jsonify({'job': key})


@reference_bp.route('/weapons/search')
@login_required
def weapons_search():
    q = request.args.get('q', '').strip()
    weapons = tblWeaponsLibrary.query.filter(
        tblWeaponsLibrary.name.ilike(f'%{q}%')
    ).order_by(tblWeaponsLibrary.name).limit(500).all()
    return jsonify([{
        'weapon_lib_id':          w.weapon_lib_id,
        'name':                   w.name,
        'weapon_category':        w.weapon_category,
        'weapon_range':           w.weapon_range,
        'damage_dice':            w.damage_dice,
        'damage_type':            w.damage_type,
        'two_handed_damage_dice': w.two_handed_damage_dice,
        'two_handed_damage_type': w.two_handed_damage_type,
        'range_normal':           w.range_normal,
        'range_long':             w.range_long,
        'properties':             w.properties,
        'mastery':                w.mastery,
        'cost':                   w.cost,
        'weight':                 w.weight,
    } for w in weapons])


# ── Armor sync ─────────────────────────────────────────────────────────────────

def sync_armor_from_api(state=None):
    api_base = get_api_base()
    version = _api_version(api_base)

    try:
        resp = requests.get(f'{api_base}/equipment-categories/armor', timeout=15)
        resp.raise_for_status()
        armor_list = resp.json().get('equipment', [])
    except Exception as e:
        return 0, 0, str(e)

    if state is not None:
        state['total'] = len(armor_list)

    added = skipped = errors = 0
    for i, entry in enumerate(armor_list):
        try:
            index = entry['index']
            if tblArmorLibrary.query.filter_by(api_index=index).first():
                skipped += 1
                continue
            # Some armor category entries (e.g. Adamantine/Mithral variants) live
            # under /magic-items/ not /equipment/ — try equipment first, fall back.
            data = None
            for endpoint in ('equipment', 'magic-items'):
                r = requests.get(f'{api_base}/{endpoint}/{index}', timeout=10)
                if r.ok and r.content:
                    try:
                        data = r.json()
                        break
                    except Exception:
                        pass
            if not data:
                skipped += 1
                continue

            ac_obj   = data.get('armor_class', {})
            cost_obj = data.get('cost', {})

            ac_base     = ac_obj.get('base', 0)
            dex_bonus   = 1 if ac_obj.get('dex_bonus') else 0
            max_dex_raw = ac_obj.get('max_bonus')
            if max_dex_raw is None and dex_bonus:
                max_dex_bonus = None
            elif max_dex_raw is not None:
                max_dex_bonus = int(max_dex_raw)
            else:
                max_dex_bonus = 0

            if version == '2024':
                cats = [c['index'] for c in data.get('equipment_categories', [])]
                armor_category = (
                    'Heavy'  if 'heavy-armor'  in cats else
                    'Medium' if 'medium-armor' in cats else
                    'Light'  if 'light-armor'  in cats else
                    'Shield' if 'shield'        in cats else
                    data.get('armor_category', '')
                )
            else:
                armor_category = data.get('armor_category', '')

            a = tblArmorLibrary(
                api_index=index,
                name=data['name'],
                armor_category=armor_category,
                armor_class_base=ac_base,
                dex_bonus=dex_bonus,
                max_dex_bonus=max_dex_bonus,
                str_minimum=data.get('str_minimum', 0) or 0,
                stealth_disadvantage=1 if data.get('stealth_disadvantage') else 0,
                weight=data.get('weight', 0) or 0,
                cost=f"{cost_obj.get('quantity', '')} {cost_obj.get('unit', '')}".strip(),
                properties=', '.join(p.get('name', '') for p in data.get('properties', [])),
                notes=data.get('desc', [''])[0] if data.get('desc') else '',
                image_url='',
                source='srd',
                created_at=_now(),
            )
            db.session.add(a)
            db.session.commit()
            added += 1
        except Exception:
            db.session.rollback()
            errors += 1
        finally:
            if state is not None:
                state.update({'done': i + 1, 'added': added, 'skipped': skipped, 'errors': errors})
    return added, skipped, errors


# ── Armor library routes ────────────────────────────────────────────────────────

@reference_bp.route('/armor/<int:armor_lib_id>/edit', methods=['POST'])
@login_required
@dm_required
def armor_edit(armor_lib_id):
    a = tblArmorLibrary.query.get_or_404(armor_lib_id)
    a.name                = request.form.get('name', a.name).strip() or a.name
    a.armor_category      = request.form.get('armor_category', a.armor_category)
    a.armor_class_base    = int(request.form.get('armor_class_base') or 0)
    a.dex_bonus           = 1 if request.form.get('dex_bonus') else 0
    raw_max = request.form.get('max_dex_bonus', '')
    a.max_dex_bonus       = None if raw_max == '' else int(raw_max)
    a.str_minimum         = int(request.form.get('str_minimum') or 0)
    a.stealth_disadvantage = 1 if request.form.get('stealth_disadvantage') else 0
    a.weight              = float(request.form.get('weight') or 0)
    a.cost                = request.form.get('cost', a.cost)
    a.properties          = request.form.get('properties', a.properties)
    a.notes               = request.form.get('notes', a.notes)
    uploaded = _save_armor_image('image_file')
    if uploaded:
        a.image_url = uploaded
    elif request.form.get('image_url', '').strip():
        a.image_url = request.form.get('image_url').strip()
    db.session.commit()
    flash(f'Updated "{a.name}".')
    return redirect(url_for('reference_bp.armor_library'))


@reference_bp.route('/armor/<int:armor_lib_id>/delete', methods=['POST'])
@login_required
@dm_required
def armor_delete(armor_lib_id):
    a = tblArmorLibrary.query.get_or_404(armor_lib_id)
    name = a.name
    db.session.delete(a)
    db.session.commit()
    flash(f'Deleted "{name}".')
    return redirect(url_for('reference_bp.armor_library'))


@reference_bp.route('/armor')
@login_required
@dm_required
def armor_library():
    total = tblArmorLibrary.query.count()
    q   = request.args.get('q',   '').strip()
    cat = request.args.get('cat', '').strip()
    src = request.args.get('src', '').strip()

    armor = tblArmorLibrary.query
    if q:
        armor = armor.filter(tblArmorLibrary.name.ilike(f'%{q}%'))
    if cat:
        armor = armor.filter(tblArmorLibrary.armor_category == cat)
    if src:
        armor = armor.filter(tblArmorLibrary.source == src)
    armor = armor.order_by(
        tblArmorLibrary.armor_category,
        tblArmorLibrary.name
    ).all()
    current_api = get_api_base()
    return render_template('ttrpg/armor_library.html',
                           armor=armor, total=total, q=q, cat=cat, src=src,
                           current_api=current_api,
                           api_options=API_OPTIONS)


@reference_bp.route('/armor/sync', methods=['POST'])
@login_required
@dm_required
def armor_sync():
    key = 'armor'
    if _sync_states.get(key, {}).get('running'):
        return jsonify({'error': 'Sync already in progress'}), 409
    state = {'total': 0, 'done': 0, 'added': 0, 'skipped': 0, 'errors': 0, 'running': True, 'message': ''}
    _sync_states[key] = state
    app = current_app._get_current_object()
    def _run():
        with app.app_context():
            added, skipped, errors = sync_armor_from_api(state=state)
            state.update({'running': False, 'message': f'{added} added, {skipped} skipped, {errors} errors.'})
    threading.Thread(target=_run, daemon=True).start()
    return jsonify({'job': key})


@reference_bp.route('/armor/add', methods=['POST'])
@login_required
@dm_required
def armor_add():
    name = request.form.get('name', '').strip()
    if not name:
        flash('Armor name is required.')
        return redirect(url_for('reference_bp.armor_library'))
    raw_max = request.form.get('max_dex_bonus', '')
    a = tblArmorLibrary(
        api_index=None,
        name=name,
        armor_category=request.form.get('armor_category', ''),
        armor_class_base=int(request.form.get('armor_class_base') or 0),
        dex_bonus=1 if request.form.get('dex_bonus') else 0,
        max_dex_bonus=None if raw_max == '' else int(raw_max),
        str_minimum=int(request.form.get('str_minimum') or 0),
        stealth_disadvantage=1 if request.form.get('stealth_disadvantage') else 0,
        weight=float(request.form.get('weight') or 0),
        cost=request.form.get('cost', '').strip(),
        properties=request.form.get('properties', '').strip(),
        notes=request.form.get('notes', '').strip(),
        image_url=_save_armor_image('image_file') or request.form.get('image_url', '').strip(),
        source='homebrew',
        created_at=_now(),
    )
    db.session.add(a)
    db.session.commit()
    flash(f'Added custom armor "{name}".')
    return redirect(url_for('reference_bp.armor_library'))


@reference_bp.route('/armor/search')
@login_required
def armor_search():
    q = request.args.get('q', '').strip()
    armor = tblArmorLibrary.query.filter(
        tblArmorLibrary.name.ilike(f'%{q}%')
    ).order_by(tblArmorLibrary.name).limit(500).all()
    return jsonify([{
        'armor_lib_id':      a.armor_lib_id,
        'name':              a.name,
        'armor_category':    a.armor_category,
        'armor_class_base':  a.armor_class_base,
        'dex_bonus':         a.dex_bonus,
        'max_dex_bonus':     a.max_dex_bonus,
        'str_minimum':       a.str_minimum,
        'stealth_disadvantage': a.stealth_disadvantage,
        'cost':              a.cost,
        'weight':            a.weight,
    } for a in armor])


# ── Spells sync ────────────────────────────────────────────────────────────────

def sync_spells_from_api(state=None):
    api_base = get_api_base()
    try:
        resp = requests.get(f'{api_base}/spells', timeout=15)
        resp.raise_for_status()
        spell_list = resp.json().get('results', [])
    except Exception as e:
        return 0, 0, str(e)

    if state is not None:
        state['total'] = len(spell_list)

    added = skipped = errors = 0
    for i, entry in enumerate(spell_list):
        try:
            index = entry['index']
            if tblSpellsLibrary.query.filter_by(api_index=index).first():
                skipped += 1
                continue
            detail = requests.get(f'{api_base}/spells/{index}', timeout=10)
            detail.raise_for_status()
            data = detail.json()

            components_list = data.get('components', [])
            material = data.get('material', '')
            if material and 'M' in components_list:
                components_str = ', '.join(components_list) + f' ({material})'
            else:
                components_str = ', '.join(components_list)

            spell = tblSpellsLibrary(
                api_index    = index,
                name         = data['name'],
                level        = data.get('level', 0),
                school       = data.get('school', {}).get('name', ''),
                casting_time = data.get('casting_time', ''),
                range_text   = data.get('range', ''),
                components   = components_str,
                duration     = data.get('duration', ''),
                concentration = 1 if data.get('concentration', False) else 0,
                ritual       = 1 if data.get('ritual', False) else 0,
                description  = '\n'.join(data.get('desc', [])),
                classes_text = ', '.join(c['name'] for c in data.get('classes', [])),
                source       = 'srd',
                created_at   = _now(),
            )
            db.session.add(spell)
            db.session.commit()
            added += 1
        except Exception:
            db.session.rollback()
            errors += 1
        finally:
            if state is not None:
                state.update({'done': i + 1, 'added': added, 'skipped': skipped, 'errors': errors})
    return added, skipped, errors


# ── Spells library routes ──────────────────────────────────────────────────────

@reference_bp.route('/spells')
@login_required
@dm_required
def spells_library():
    total = tblSpellsLibrary.query.count()
    q      = request.args.get('q',      '').strip()
    level  = request.args.get('level',  '').strip()
    school = request.args.get('school', '').strip()
    src    = request.args.get('src',    '').strip()

    spells = tblSpellsLibrary.query
    if q:
        spells = spells.filter(tblSpellsLibrary.name.ilike(f'%{q}%'))
    if level != '':
        try:
            spells = spells.filter(tblSpellsLibrary.level == int(level))
        except ValueError:
            pass
    if school:
        spells = spells.filter(tblSpellsLibrary.school == school)
    if src:
        spells = spells.filter(tblSpellsLibrary.source == src)
    spells = spells.order_by(tblSpellsLibrary.level, tblSpellsLibrary.name).all()
    current_api = get_api_base()
    return render_template('ttrpg/spells_library.html',
                           spells=spells, total=total,
                           q=q, level=level, school=school, src=src,
                           current_api=current_api,
                           api_options=API_OPTIONS)


@reference_bp.route('/spells/sync', methods=['POST'])
@login_required
@dm_required
def spells_sync():
    key = 'spells'
    if _sync_states.get(key, {}).get('running'):
        return jsonify({'error': 'Sync already in progress'}), 409
    state = {'total': 0, 'done': 0, 'added': 0, 'skipped': 0, 'errors': 0, 'running': True, 'message': ''}
    _sync_states[key] = state
    app = current_app._get_current_object()
    def _run():
        with app.app_context():
            added, skipped, errors = sync_spells_from_api(state=state)
            state.update({'running': False, 'message': f'{added} added, {skipped} skipped, {errors} errors.'})
    threading.Thread(target=_run, daemon=True).start()
    return jsonify({'job': key})


@reference_bp.route('/spells/add', methods=['POST'])
@login_required
@dm_required
def spell_add():
    name = request.form.get('name', '').strip()
    if not name:
        flash('Spell name is required.')
        return redirect(url_for('reference_bp.spells_library'))
    spell = tblSpellsLibrary(
        api_index    = None,
        name         = name,
        level        = int(request.form.get('level', 0) or 0),
        school       = request.form.get('school', '').strip(),
        casting_time = request.form.get('casting_time', '').strip(),
        range_text   = request.form.get('range_text', '').strip(),
        components   = request.form.get('components', '').strip(),
        duration     = request.form.get('duration', '').strip(),
        concentration = 1 if request.form.get('concentration') else 0,
        ritual       = 1 if request.form.get('ritual') else 0,
        description  = request.form.get('description', '').strip(),
        classes_text = request.form.get('classes_text', '').strip(),
        source       = 'homebrew',
        created_at   = _now(),
    )
    db.session.add(spell)
    db.session.commit()
    flash(f'Added custom spell "{name}".')
    return redirect(url_for('reference_bp.spells_library'))


@reference_bp.route('/spells/<int:spell_lib_id>/delete', methods=['POST'])
@login_required
@dm_required
def spell_delete(spell_lib_id):
    spell = tblSpellsLibrary.query.get_or_404(spell_lib_id)
    if spell.source != 'homebrew':
        flash('Only custom spells can be deleted.')
        return redirect(url_for('reference_bp.spells_library'))
    name = spell.name
    db.session.delete(spell)
    db.session.commit()
    flash(f'Deleted "{name}".')
    return redirect(url_for('reference_bp.spells_library'))


@reference_bp.route('/spells/search')
@login_required
def spells_search():
    q      = request.args.get('q',      '').strip()
    level  = request.args.get('level',  '').strip()
    school = request.args.get('school', '').strip()
    src    = request.args.get('src',    '').strip()
    limit  = int(request.args.get('limit', 20))

    spells = tblSpellsLibrary.query
    if q:
        spells = spells.filter(tblSpellsLibrary.name.ilike(f'%{q}%'))
    if level != '':
        try:
            spells = spells.filter(tblSpellsLibrary.level == int(level))
        except ValueError:
            pass
    if school:
        spells = spells.filter(tblSpellsLibrary.school == school)
    if src:
        spells = spells.filter(tblSpellsLibrary.source == src)
    spells = spells.order_by(tblSpellsLibrary.level, tblSpellsLibrary.name).limit(limit).all()
    return jsonify([{
        'spell_lib_id': s.spell_lib_id,
        'name':         s.name,
        'level':        s.level,
        'school':       s.school,
        'casting_time': s.casting_time,
        'range_text':   s.range_text,
        'components':   s.components,
        'duration':     s.duration,
        'concentration': s.concentration,
        'ritual':       s.ritual,
        'description':  s.description,
        'classes_text': s.classes_text,
        'source':       s.source,
    } for s in spells])


# ── Skills sync ────────────────────────────────────────────────────────────────

def sync_skills_from_api(state=None):
    api_base = get_api_base()
    try:
        resp = requests.get(f'{api_base}/skills', timeout=15)
        resp.raise_for_status()
        skill_list = resp.json().get('results', [])
    except Exception as e:
        return 0, 0, str(e)

    if state is not None:
        state['total'] = len(skill_list)

    added = skipped = errors = 0
    for i, entry in enumerate(skill_list):
        try:
            index = entry['index']
            if tblSkillsLibrary.query.filter_by(api_index=index).first():
                skipped += 1
                continue
            detail = requests.get(f'{api_base}/skills/{index}', timeout=10)
            detail.raise_for_status()
            data = detail.json()

            ability_obj = data.get('ability_score', {})
            ability_score = ability_obj.get('name', '') or ability_obj.get('index', '').upper()

            skill = tblSkillsLibrary(
                api_index     = index,
                name          = data['name'],
                ability_score = ability_score,
                description   = '\n'.join(data.get('desc', [])),
                source        = 'srd',
                created_at    = _now(),
            )
            db.session.add(skill)
            db.session.commit()
            added += 1
        except Exception:
            db.session.rollback()
            errors += 1
        finally:
            if state is not None:
                state.update({'done': i + 1, 'added': added, 'skipped': skipped, 'errors': errors})
    return added, skipped, errors


# ── Skills library routes ──────────────────────────────────────────────────────

@reference_bp.route('/skills')
@login_required
@dm_required
def skills_library():
    total = tblSkillsLibrary.query.count()
    q   = request.args.get('q',   '').strip()
    src = request.args.get('src', '').strip()

    skills = tblSkillsLibrary.query
    if q:
        skills = skills.filter(tblSkillsLibrary.name.ilike(f'%{q}%'))
    if src:
        skills = skills.filter(tblSkillsLibrary.source == src)
    skills = skills.order_by(tblSkillsLibrary.ability_score, tblSkillsLibrary.name).all()
    current_api = get_api_base()
    return render_template('ttrpg/skills_library.html',
                           skills=skills, total=total, q=q, src=src,
                           current_api=current_api,
                           api_options=API_OPTIONS)


@reference_bp.route('/skills/sync', methods=['POST'])
@login_required
@dm_required
def skills_sync():
    key = 'skills'
    if _sync_states.get(key, {}).get('running'):
        return jsonify({'error': 'Sync already in progress'}), 409
    state = {'total': 0, 'done': 0, 'added': 0, 'skipped': 0, 'errors': 0, 'running': True, 'message': ''}
    _sync_states[key] = state
    app = current_app._get_current_object()
    def _run():
        with app.app_context():
            added, skipped, errors = sync_skills_from_api(state=state)
            state.update({'running': False, 'message': f'{added} added, {skipped} skipped, {errors} errors.'})
    threading.Thread(target=_run, daemon=True).start()
    return jsonify({'job': key})


@reference_bp.route('/skills/add', methods=['POST'])
@login_required
@dm_required
def skill_add_to_lib():
    name = request.form.get('name', '').strip()
    if not name:
        flash('Skill name is required.')
        return redirect(url_for('reference_bp.skills_library'))
    skill = tblSkillsLibrary(
        api_index     = None,
        name          = name,
        ability_score = request.form.get('ability_score', '').strip(),
        description   = request.form.get('description', '').strip(),
        source        = 'homebrew',
        created_at    = _now(),
    )
    db.session.add(skill)
    db.session.commit()
    flash(f'Added custom skill "{name}".')
    return redirect(url_for('reference_bp.skills_library'))


@reference_bp.route('/skills/<int:skill_lib_id>/delete', methods=['POST'])
@login_required
@dm_required
def skill_lib_delete(skill_lib_id):
    skill = tblSkillsLibrary.query.get_or_404(skill_lib_id)
    if skill.source != 'homebrew':
        flash('Only custom skills can be deleted.')
        return redirect(url_for('reference_bp.skills_library'))
    name = skill.name
    db.session.delete(skill)
    db.session.commit()
    flash(f'Deleted "{name}".')
    return redirect(url_for('reference_bp.skills_library'))


@reference_bp.route('/skills/search')
@login_required
def skills_search():
    q = request.args.get('q', '').strip()
    skills = tblSkillsLibrary.query.filter(
        tblSkillsLibrary.name.ilike(f'%{q}%')
    ).order_by(tblSkillsLibrary.ability_score, tblSkillsLibrary.name).limit(30).all()
    return jsonify([{
        'skill_lib_id': s.skill_lib_id,
        'name':         s.name,
        'ability_score': s.ability_score,
        'description':  s.description,
        'source':       s.source,
    } for s in skills])


# ── Races sync ─────────────────────────────────────────────────────────────────

def sync_races_from_api(state=None):
    api_base = get_api_base()
    try:
        resp = requests.get(f'{api_base}/races', timeout=15)
        resp.raise_for_status()
        race_list = resp.json().get('results', [])
    except Exception as e:
        return 0, 0, str(e)

    if state is not None:
        state['total'] = len(race_list)

    added = skipped = errors = 0
    for i, entry in enumerate(race_list):
        try:
            index = entry['index']
            if tblRacesLibrary.query.filter_by(api_index=index).first():
                skipped += 1
                continue
            detail = requests.get(f'{api_base}/races/{index}', timeout=10)
            detail.raise_for_status()
            data = detail.json()

            ability_bonuses = ', '.join(
                f"+{ab['bonus']} {ab['ability_score']['name']}"
                for ab in data.get('ability_bonuses', [])
            )

            race = tblRacesLibrary(
                api_index      = index,
                name           = data['name'],
                speed          = data.get('speed', 30),
                size           = data.get('size', ''),
                ability_bonuses = ability_bonuses,
                traits_text    = '\n'.join(t['name'] for t in data.get('traits', [])),
                languages      = ', '.join(l['name'] for l in data.get('languages', [])),
                description    = data.get('alignment', ''),
                source         = 'srd',
                created_at     = _now(),
            )
            db.session.add(race)
            db.session.commit()
            added += 1
        except Exception:
            db.session.rollback()
            errors += 1
        finally:
            if state is not None:
                state.update({'done': i + 1, 'added': added, 'skipped': skipped, 'errors': errors})
    return added, skipped, errors


# ── Races library routes ───────────────────────────────────────────────────────

@reference_bp.route('/races')
@login_required
@dm_required
def races_library():
    total = tblRacesLibrary.query.count()
    q   = request.args.get('q',   '').strip()
    src = request.args.get('src', '').strip()

    races = tblRacesLibrary.query
    if q:
        races = races.filter(tblRacesLibrary.name.ilike(f'%{q}%'))
    if src:
        races = races.filter(tblRacesLibrary.source == src)
    races = races.order_by(tblRacesLibrary.name).all()
    current_api = get_api_base()
    return render_template('ttrpg/races_library.html',
                           races=races, total=total, q=q, src=src,
                           current_api=current_api,
                           api_options=API_OPTIONS)


@reference_bp.route('/races/sync', methods=['POST'])
@login_required
@dm_required
def races_sync():
    key = 'races'
    if _sync_states.get(key, {}).get('running'):
        return jsonify({'error': 'Sync already in progress'}), 409
    state = {'total': 0, 'done': 0, 'added': 0, 'skipped': 0, 'errors': 0, 'running': True, 'message': ''}
    _sync_states[key] = state
    app = current_app._get_current_object()
    def _run():
        with app.app_context():
            added, skipped, errors = sync_races_from_api(state=state)
            state.update({'running': False, 'message': f'{added} added, {skipped} skipped, {errors} errors.'})
    threading.Thread(target=_run, daemon=True).start()
    return jsonify({'job': key})


@reference_bp.route('/races/add', methods=['POST'])
@login_required
@dm_required
def race_add():
    name = request.form.get('name', '').strip()
    if not name:
        flash('Race name is required.')
        return redirect(url_for('reference_bp.races_library'))
    race = tblRacesLibrary(
        api_index       = None,
        name            = name,
        speed           = int(request.form.get('speed', 30) or 30),
        size            = request.form.get('size', '').strip(),
        ability_bonuses = request.form.get('ability_bonuses', '').strip(),
        traits_text     = request.form.get('traits_text', '').strip(),
        languages       = request.form.get('languages', '').strip(),
        description     = request.form.get('description', '').strip(),
        source          = 'homebrew',
        created_at      = _now(),
    )
    db.session.add(race)
    db.session.commit()
    flash(f'Added custom race "{name}".')
    return redirect(url_for('reference_bp.races_library'))


@reference_bp.route('/races/<int:race_lib_id>/delete', methods=['POST'])
@login_required
@dm_required
def race_delete(race_lib_id):
    race = tblRacesLibrary.query.get_or_404(race_lib_id)
    if race.source != 'homebrew':
        flash('Only custom races can be deleted.')
        return redirect(url_for('reference_bp.races_library'))
    name = race.name
    db.session.delete(race)
    db.session.commit()
    flash(f'Deleted "{name}".')
    return redirect(url_for('reference_bp.races_library'))


# ── Equipment Library ───────────────────────────────────────────────────────────

SKIP_EQUIPMENT_CATEGORIES = {'armor', 'weapon', 'weapons', 'armor and shields'}

def sync_equipment_from_api(state=None):
    api_base = get_api_base()
    try:
        resp = requests.get(f'{api_base}/equipment', timeout=15)
        resp.raise_for_status()
        eq_list = resp.json().get('results', [])
    except Exception as e:
        return 0, 0, str(e)

    if state is not None:
        state['total'] = len(eq_list)

    added = skipped = errors = 0
    for i, entry in enumerate(eq_list):
        try:
            index = entry['index']
            if tblEquipmentLibrary.query.filter_by(api_index=index).first():
                skipped += 1
                continue
            r = requests.get(f'{api_base}/equipment/{index}', timeout=10)
            if not r.ok or not r.content:
                skipped += 1
                continue
            data = r.json()

            cat = (data.get('equipment_category') or {}).get('name', '')
            if cat.lower() in SKIP_EQUIPMENT_CATEGORIES:
                skipped += 1
                continue

            subcat = (data.get('gear_category') or
                      data.get('tool_category') or
                      data.get('vehicle_category') or {})
            if isinstance(subcat, dict):
                subcat = subcat.get('name', '')
            else:
                subcat = ''

            cost_obj = data.get('cost', {})
            cost_str = f"{cost_obj.get('quantity', 0)} {cost_obj.get('unit', 'gp')}" if cost_obj else ''

            item = tblEquipmentLibrary(
                api_index   = index,
                name        = data.get('name', index),
                category    = cat,
                subcategory = subcat,
                weight      = float(data.get('weight', 0) or 0),
                cost        = cost_str,
                description = '\n'.join(data.get('desc', [])),
                source      = 'srd',
                created_at  = _now(),
            )
            db.session.add(item)
            db.session.commit()
            added += 1
        except Exception:
            db.session.rollback()
            errors += 1
        finally:
            if state is not None:
                state.update({'done': i + 1, 'added': added, 'skipped': skipped, 'errors': errors})

    return added, skipped, errors


@reference_bp.route('/equipment')
@login_required
@dm_required
def equipment_library():
    total = tblEquipmentLibrary.query.count()
    q    = request.args.get('q',   '').strip()
    cat  = request.args.get('cat', '').strip()
    src  = request.args.get('src', '').strip()

    query = tblEquipmentLibrary.query
    if q:   query = query.filter(tblEquipmentLibrary.name.ilike(f'%{q}%'))
    if cat: query = query.filter(tblEquipmentLibrary.category == cat)
    if src: query = query.filter(tblEquipmentLibrary.source == src)
    items = query.order_by(tblEquipmentLibrary.category, tblEquipmentLibrary.name).all()

    categories = sorted({i.category for i in tblEquipmentLibrary.query.all() if i.category})
    current_api = get_api_base()
    return render_template('ttrpg/equipment_library.html',
                           items=items, total=total, q=q, cat=cat, src=src,
                           categories=categories,
                           current_api=current_api, api_options=API_OPTIONS)


@reference_bp.route('/equipment/sync', methods=['POST'])
@login_required
@dm_required
def equipment_sync():
    key = 'equipment'
    if _sync_states.get(key, {}).get('running'):
        return jsonify({'error': 'Sync already in progress'}), 409
    state = {'total': 0, 'done': 0, 'added': 0, 'skipped': 0, 'errors': 0, 'running': True, 'message': ''}
    _sync_states[key] = state
    app = current_app._get_current_object()
    def _run():
        with app.app_context():
            added, skipped, errors = sync_equipment_from_api(state=state)
            state.update({'running': False, 'message': f'{added} added, {skipped} skipped, {errors} errors.'})
    threading.Thread(target=_run, daemon=True).start()
    return jsonify({'job': key})


@reference_bp.route('/sync/status/<job_type>')
@login_required
def sync_status(job_type):
    state = _sync_states.get(job_type, {})
    if not state:
        return jsonify({'running': False, 'total': 0, 'done': 0, 'message': ''})
    return jsonify(dict(state))


@reference_bp.route('/equipment/add', methods=['POST'])
@login_required
@dm_required
def equipment_add():
    name = request.form.get('name', '').strip()
    if not name:
        flash('Item name is required.')
        return redirect(url_for('reference_bp.equipment_library'))
    item = tblEquipmentLibrary(
        api_index   = None,
        name        = name,
        category    = request.form.get('category', '').strip(),
        subcategory = request.form.get('subcategory', '').strip(),
        weight      = float(request.form.get('weight', 0) or 0),
        cost        = request.form.get('cost', '').strip(),
        description = request.form.get('description', '').strip(),
        source      = 'homebrew',
        created_at  = _now(),
    )
    db.session.add(item)
    db.session.commit()
    flash(f'Added "{name}".')
    return redirect(url_for('reference_bp.equipment_library'))


@reference_bp.route('/equipment/<int:equipment_lib_id>/delete', methods=['POST'])
@login_required
@dm_required
def equipment_delete(equipment_lib_id):
    item = tblEquipmentLibrary.query.get_or_404(equipment_lib_id)
    if item.source != 'homebrew':
        flash('Only custom items can be deleted.')
        return redirect(url_for('reference_bp.equipment_library'))
    name = item.name
    db.session.delete(item)
    db.session.commit()
    flash(f'Deleted "{name}".')
    return redirect(url_for('reference_bp.equipment_library'))


@reference_bp.route('/equipment/search')
@login_required
def equipment_search():
    q = request.args.get('q', '').strip()
    items = tblEquipmentLibrary.query.filter(
        tblEquipmentLibrary.name.ilike(f'%{q}%')
    ).order_by(tblEquipmentLibrary.name).limit(500).all()
    return jsonify([{
        'equipment_lib_id': i.equipment_lib_id,
        'name':             i.name,
        'category':         i.category,
        'subcategory':      i.subcategory,
        'weight':           i.weight,
        'cost':             i.cost,
        'description':      i.description,
    } for i in items])


# ── Classes sync ────────────────────────────────────────────────────────────────

def sync_classes_from_api(state=None):
    api_base = get_api_base()
    try:
        resp = requests.get(f'{api_base}/classes', timeout=15)
        resp.raise_for_status()
        class_list = resp.json().get('results', [])
    except Exception as e:
        return 0, 0, str(e)

    if state is not None:
        state['total'] = len(class_list)

    added = skipped = errors = 0
    for i, entry in enumerate(class_list):
        try:
            index = entry['index']
            if tblClassesLibrary.query.filter_by(api_index=index).first():
                skipped += 1
                continue
            detail = requests.get(f'{api_base}/classes/{index}', timeout=10)
            detail.raise_for_status()
            data = detail.json()

            saving_throws = ', '.join(st['name'] for st in data.get('saving_throws', []))

            # All proficiencies except saving-throw entries
            profs = [p['name'] for p in data.get('proficiencies', [])
                     if not p['name'].startswith('Saving Throw')]
            proficiencies = ', '.join(profs)

            # Skill choices description
            skill_choices = ''
            for choice in data.get('proficiency_choices', []):
                desc = choice.get('desc', '')
                if desc:
                    skill_choices = desc
                    break

            subclasses = ', '.join(sc['name'] for sc in data.get('subclasses', []))

            spell_obj = data.get('spellcasting', {})
            spellcasting_ability = (spell_obj.get('spellcasting_ability', {}) or {}).get('name', '')

            cls = tblClassesLibrary(
                api_index            = index,
                name                 = data['name'],
                hit_die              = data.get('hit_die', 8),
                saving_throws        = saving_throws,
                proficiencies        = proficiencies,
                skill_choices        = skill_choices,
                subclasses           = subclasses,
                spellcasting_ability = spellcasting_ability,
                description          = '',
                source               = 'srd',
                created_at           = _now(),
            )
            db.session.add(cls)
            db.session.commit()
            added += 1
        except Exception:
            db.session.rollback()
            errors += 1
        finally:
            if state is not None:
                state.update({'done': i + 1, 'added': added, 'skipped': skipped, 'errors': errors})
    return added, skipped, errors


# ── Classes library routes ─────────────────────────────────────────────────────

@reference_bp.route('/classes')
@login_required
@dm_required
def classes_library():
    total = tblClassesLibrary.query.count()
    q   = request.args.get('q',   '').strip()
    src = request.args.get('src', '').strip()

    classes = tblClassesLibrary.query
    if q:
        classes = classes.filter(tblClassesLibrary.name.ilike(f'%{q}%'))
    if src:
        classes = classes.filter(tblClassesLibrary.source == src)
    classes = classes.order_by(tblClassesLibrary.name).all()
    current_api = get_api_base()
    return render_template('ttrpg/classes_library.html',
                           classes=classes, total=total, q=q, src=src,
                           current_api=current_api, api_options=API_OPTIONS)


@reference_bp.route('/classes/sync', methods=['POST'])
@login_required
@dm_required
def classes_sync():
    key = 'classes'
    if _sync_states.get(key, {}).get('running'):
        return jsonify({'error': 'Sync already in progress'}), 409
    state = {'total': 0, 'done': 0, 'added': 0, 'skipped': 0, 'errors': 0, 'running': True, 'message': ''}
    _sync_states[key] = state
    app = current_app._get_current_object()
    def _run():
        with app.app_context():
            added, skipped, errors = sync_classes_from_api(state=state)
            state.update({'running': False, 'message': f'{added} added, {skipped} skipped, {errors} errors.'})
    threading.Thread(target=_run, daemon=True).start()
    return jsonify({'job': key})


@reference_bp.route('/classes/add', methods=['POST'])
@login_required
@dm_required
def class_add():
    name = request.form.get('name', '').strip()
    if not name:
        flash('Class name is required.')
        return redirect(url_for('reference_bp.classes_library'))
    cls = tblClassesLibrary(
        api_index            = None,
        name                 = name,
        hit_die              = int(request.form.get('hit_die', 8) or 8),
        saving_throws        = request.form.get('saving_throws', '').strip(),
        proficiencies        = request.form.get('proficiencies', '').strip(),
        skill_choices        = request.form.get('skill_choices', '').strip(),
        subclasses           = request.form.get('subclasses', '').strip(),
        spellcasting_ability = request.form.get('spellcasting_ability', '').strip(),
        description          = request.form.get('description', '').strip(),
        source               = 'homebrew',
        created_at           = _now(),
    )
    db.session.add(cls)
    db.session.commit()
    flash(f'Added custom class "{name}".')
    return redirect(url_for('reference_bp.classes_library'))


@reference_bp.route('/classes/<int:class_lib_id>/delete', methods=['POST'])
@login_required
@dm_required
def class_delete(class_lib_id):
    cls = tblClassesLibrary.query.get_or_404(class_lib_id)
    if cls.source != 'homebrew':
        flash('Only custom classes can be deleted.')
        return redirect(url_for('reference_bp.classes_library'))
    name = cls.name
    db.session.delete(cls)
    db.session.commit()
    flash(f'Deleted "{name}".')
    return redirect(url_for('reference_bp.classes_library'))


@reference_bp.route('/races/search')
@login_required
def races_search():
    q = request.args.get('q', '').strip()
    races = tblRacesLibrary.query.filter(
        tblRacesLibrary.name.ilike(f'%{q}%')
    ).order_by(tblRacesLibrary.name).limit(500).all()
    return jsonify([{
        'race_lib_id':    r.race_lib_id,
        'name':           r.name,
        'speed':          r.speed,
        'size':           r.size,
        'ability_bonuses': r.ability_bonuses,
        'traits_text':    r.traits_text,
        'languages':      r.languages,
        'description':    r.description,
    } for r in races])


@reference_bp.route('/classes/search')
@login_required
def classes_search():
    q = request.args.get('q', '').strip()
    classes = tblClassesLibrary.query.filter(
        tblClassesLibrary.name.ilike(f'%{q}%')
    ).order_by(tblClassesLibrary.name).limit(500).all()
    return jsonify([{
        'class_lib_id':         c.class_lib_id,
        'name':                 c.name,
        'hit_die':              c.hit_die,
        'saving_throws':        c.saving_throws,
        'proficiencies':        c.proficiencies,
        'skill_choices':        c.skill_choices,
        'subclasses':           c.subclasses,
        'spellcasting_ability': c.spellcasting_ability,
        'description':          c.description,
    } for c in classes])
