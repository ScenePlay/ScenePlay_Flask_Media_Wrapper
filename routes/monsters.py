import json
import threading
import requests
from datetime import datetime
from flask import (Blueprint, render_template, redirect, url_for,
                   request, flash, jsonify, current_app)
from flask_login import login_required
from extensions import db
from models.ttrpg import tblMonsterTemplates, tblSessionMonsters, tblSessions
from routes.auth import dm_required

monsters_bp = Blueprint('monsters_bp', __name__, url_prefix='/ttrpg/monsters')
_sync_states = {}

API_BASE = 'https://www.dnd5eapi.co/api/2014'
CONDITIONS = {
    'Blinded':       "Can't see. Auto-fails checks requiring sight. Attacks against: advantage. Own attacks: disadvantage.",
    'Charmed':       "Can't attack the charmer or target them with harmful effects. Charmer has advantage on social checks against you.",
    'Deafened':      "Can't hear. Auto-fails checks requiring hearing.",
    'Exhaustion':    "1: Disadvantage on ability checks  2: Speed halved  3: Disadvantage on attacks & saves  4: HP max halved  5: Speed = 0  6: Death",
    'Frightened':    "Disadvantage on ability checks and attack rolls while the source of fear is in line of sight. Can't willingly move closer to the source.",
    'Grappled':      "Speed becomes 0. Ends if the grappler is incapacitated or you are moved out of their reach.",
    'Incapacitated': "Can't take actions or reactions.",
    'Invisible':     "Can't be seen without magic or special senses. Own attack rolls: advantage. Attacks against: disadvantage.",
    'Paralyzed':     "Incapacitated; can't move or speak. Auto-fails STR & DEX saves. Attacks against: advantage. Hits within 5 ft are critical hits.",
    'Petrified':     "Transformed to a solid object. Incapacitated; unaware of surroundings. Auto-fails STR & DEX saves. Resistance to all damage; immune to poison and disease.",
    'Poisoned':      "Disadvantage on attack rolls and ability checks.",
    'Prone':         "Can only crawl. Disadvantage on attack rolls. Melee attacks against: advantage. Ranged attacks against: disadvantage.",
    'Restrained':    "Speed = 0. Own attack rolls: disadvantage. Attacks against: advantage. DEX saves: disadvantage.",
    'Stunned':       "Incapacitated; can't move; can only speak falteringly. Auto-fails STR & DEX saves. Attacks against: advantage.",
    'Unconscious':   "Incapacitated; can't move or speak; unaware of surroundings. Falls prone. Auto-fails STR & DEX saves. Attacks against: advantage. Hits within 5 ft are critical hits.",
}


def _now():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _cr_display(cr):
    """Convert numeric CR to display string (0.5 → '1/2', 0.25 → '1/4')."""
    mapping = {0.125: '1/8', 0.25: '1/4', 0.5: '1/2'}
    try:
        f = float(cr)
        return mapping.get(f, str(int(f)) if f == int(f) else str(f))
    except (ValueError, TypeError):
        return str(cr)


def _cr_to_float(cr_str):
    """Convert stored CR text to float for range comparisons."""
    mapping = {'1/8': 0.125, '1/4': 0.25, '1/2': 0.5}
    if cr_str in mapping:
        return mapping[cr_str]
    try:
        return float(cr_str)
    except (ValueError, TypeError):
        return 0.0


def _extract_ac(armor_class):
    """Pull the first AC value from the API's armor_class list."""
    if isinstance(armor_class, list) and armor_class:
        return armor_class[0].get('value', 10)
    if isinstance(armor_class, int):
        return armor_class
    return 10


# ── Sync all monsters from the SRD API ────────────────────────────────────────

def sync_monsters_from_api(state=None):
    from routes.reference import get_api_base
    api_base = get_api_base()
    try:
        resp = requests.get(f'{api_base}/monsters', timeout=15)
        resp.raise_for_status()
        monster_list = resp.json().get('results', [])
    except Exception as e:
        return 0, 0, str(e)

    if state is not None:
        state['total'] = len(monster_list)

    added = skipped = errors = 0
    for i, entry in enumerate(monster_list):
        try:
            index = entry['index']
            if tblMonsterTemplates.query.filter_by(api_index=index).first():
                skipped += 1
                continue
            detail = requests.get(f'{api_base}/monsters/{index}', timeout=10)
            detail.raise_for_status()
            data = detail.json()

            cr_raw = data.get('challenge_rating', 0)
            cr_str = _cr_display(cr_raw)

            t = tblMonsterTemplates(
                api_index    = index,
                name         = data.get('name', index),
                cr           = cr_str,
                monster_type = data.get('type', ''),
                size         = data.get('size', ''),
                hp_max       = data.get('hit_points', 0),
                ac           = _extract_ac(data.get('armor_class', [])),
                source       = 'srd',
                stats_json   = json.dumps(data),
                created_at   = _now(),
            )
            db.session.add(t)
            db.session.commit()
            added += 1
        except Exception:
            errors += 1
        finally:
            if state is not None:
                state.update({'done': i + 1, 'added': added, 'skipped': skipped, 'errors': errors})

    return added, skipped, errors


# ── Library ────────────────────────────────────────────────────────────────────

@monsters_bp.route('/')
@login_required
@dm_required
def library():
    from routes.reference import get_api_base, API_OPTIONS
    synced = tblMonsterTemplates.query.count()
    sessions = tblSessions.query.filter(
        tblSessions.status.in_(['planning', 'active'])
    ).order_by(tblSessions.title).all()
    raw_types = db.session.query(tblMonsterTemplates.monster_type).distinct().all()
    monster_types = sorted(t[0].lower() for t in raw_types if t[0])
    current_api = get_api_base()
    return render_template('ttrpg/monsters.html',
                           synced=synced,
                           sessions=sessions,
                           conditions=CONDITIONS,
                           monster_types=monster_types,
                           current_api=current_api,
                           api_options=API_OPTIONS)


# ── AJAX search ───────────────────────────────────────────────────────────────

@monsters_bp.route('/search')
@login_required
@dm_required
def search():
    q           = request.args.get('q', '').strip()
    type_filter = request.args.get('type', '').strip().lower()
    size_filter = request.args.get('size', '').strip()
    src_filter  = request.args.get('source', '').strip()
    cr_min      = request.args.get('cr_min', '')
    cr_max      = request.args.get('cr_max', '')
    limit       = min(int(request.args.get('limit', 50)), 500)

    query = tblMonsterTemplates.query

    if q:
        query = query.filter(tblMonsterTemplates.name.ilike(f'%{q}%'))
    if type_filter:
        query = query.filter(tblMonsterTemplates.monster_type.ilike(type_filter))
    if size_filter:
        query = query.filter(tblMonsterTemplates.size.ilike(size_filter))
    if src_filter in ('srd', 'homebrew'):
        query = query.filter(tblMonsterTemplates.source == src_filter)

    monsters = query.order_by(tblMonsterTemplates.name).all()

    if cr_min != '' or cr_max != '':
        cr_min_f = float(cr_min) if cr_min != '' else 0.0
        cr_max_f = float(cr_max) if cr_max != '' else 30.0
        monsters = [m for m in monsters if cr_min_f <= _cr_to_float(m.cr) <= cr_max_f]

    monsters = monsters[:limit]

    return jsonify([{
        'template_id': m.template_id,
        'name': m.name,
        'cr': m.cr,
        'type': m.monster_type,
        'size': m.size,
        'hp_max': m.hp_max,
        'ac': m.ac,
        'source': m.source,
    } for m in monsters])


# ── Monster detail (AJAX) ─────────────────────────────────────────────────────

@monsters_bp.route('/<int:template_id>/detail')
@login_required
@dm_required
def detail(template_id):
    m = tblMonsterTemplates.query.get_or_404(template_id)
    data = json.loads(m.stats_json or '{}')
    return jsonify({'ok': True, 'name': m.name, 'stats': data,
                    'cr': m.cr, 'hp_max': m.hp_max, 'ac': m.ac,
                    'source': m.source})


# ── Add to session ────────────────────────────────────────────────────────────

@monsters_bp.route('/<int:template_id>/add-to-session', methods=['POST'])
@login_required
@dm_required
def add_to_session(template_id):
    m = tblMonsterTemplates.query.get_or_404(template_id)
    session_id = request.form.get('session_id', type=int)
    count = max(1, min(20, request.form.get('count', 1, type=int)))
    hp_override = request.form.get('hp_override', type=int)

    if not session_id:
        return jsonify({'ok': False, 'error': 'No session selected'}), 400

    sess = tblSessions.query.get_or_404(session_id)
    existing_count = tblSessionMonsters.query.filter_by(
        session_id=session_id, template_id=template_id).count()

    hp = hp_override if hp_override and hp_override > 0 else m.hp_max

    created = []
    for i in range(count):
        num = existing_count + i + 1
        display = m.name if count == 1 and existing_count == 0 else f'{m.name} {num}'
        sm = tblSessionMonsters(
            session_id   = session_id,
            template_id  = template_id,
            display_name = display,
            hp_current   = hp,
            hp_max       = hp,
            ac           = m.ac,
            initiative   = 0,
            conditions   = '[]',
            is_alive     = 1,
            sort_order   = tblSessionMonsters.query.filter_by(session_id=session_id).count(),
        )
        db.session.add(sm)
        db.session.flush()
        created.append({'monster_id': sm.monster_id, 'display_name': display})

    db.session.commit()
    return jsonify({'ok': True, 'created': created, 'session_title': sess.title})


# ── Sync trigger ──────────────────────────────────────────────────────────────

@monsters_bp.route('/sync', methods=['POST'])
@login_required
@dm_required
def sync():
    key = 'monsters'
    if _sync_states.get(key, {}).get('running'):
        return jsonify({'error': 'Sync already in progress'}), 409
    state = {'total': 0, 'done': 0, 'added': 0, 'skipped': 0, 'errors': 0, 'running': True, 'message': ''}
    _sync_states[key] = state
    app = current_app._get_current_object()
    def _run():
        with app.app_context():
            added, skipped, errors = sync_monsters_from_api(state=state)
            state.update({'running': False, 'message': f'{added} added, {skipped} skipped, {errors} errors.'})
    threading.Thread(target=_run, daemon=True).start()
    return jsonify({'job': key})


@monsters_bp.route('/sync/status')
@login_required
def sync_status():
    state = _sync_states.get('monsters', {})
    if not state:
        return jsonify({'running': False, 'total': 0, 'done': 0, 'message': ''})
    return jsonify(dict(state))


# ── Homebrew create ───────────────────────────────────────────────────────────

@monsters_bp.route('/homebrew/new', methods=['GET', 'POST'])
@login_required
@dm_required
def homebrew_new():
    error = None
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        if not name:
            error = 'Monster name is required.'
        else:
            stats = {
                'name': name,
                'size': request.form.get('size', ''),
                'type': request.form.get('monster_type', ''),
                'alignment': request.form.get('alignment', ''),
                'hit_points': int(request.form.get('hp_max', 0) or 0),
                'armor_class': [{'value': int(request.form.get('ac', 10) or 10), 'type': 'natural'}],
                'speed': {'walk': request.form.get('speed', '30 ft.')},
                'strength': int(request.form.get('str_val', 10) or 10),
                'dexterity': int(request.form.get('dex_val', 10) or 10),
                'constitution': int(request.form.get('con_val', 10) or 10),
                'intelligence': int(request.form.get('int_val', 10) or 10),
                'wisdom': int(request.form.get('wis_val', 10) or 10),
                'charisma': int(request.form.get('cha_val', 10) or 10),
                'challenge_rating': request.form.get('cr', '0'),
                'xp': int(request.form.get('xp', 0) or 0),
                'languages': request.form.get('languages', ''),
                'senses': {},
                'special_abilities': [],
                'actions': [],
                'notes': request.form.get('notes', ''),
            }
            t = tblMonsterTemplates(
                api_index    = None,
                name         = name,
                cr           = request.form.get('cr', '0'),
                monster_type = request.form.get('monster_type', ''),
                size         = request.form.get('size', ''),
                hp_max       = int(request.form.get('hp_max', 0) or 0),
                ac           = int(request.form.get('ac', 10) or 10),
                source       = 'homebrew',
                stats_json   = json.dumps(stats),
                created_at   = _now(),
            )
            db.session.add(t)
            db.session.commit()
            flash(f'Homebrew monster "{name}" created.')
            return redirect(url_for('monsters_bp.library'))

    return render_template('ttrpg/monster_homebrew.html', error=error)


@monsters_bp.route('/homebrew/<int:template_id>/delete', methods=['POST'])
@login_required
@dm_required
def homebrew_delete(template_id):
    m = tblMonsterTemplates.query.get_or_404(template_id)
    if m.source != 'homebrew':
        flash('Cannot delete SRD monsters.')
        return redirect(url_for('monsters_bp.library'))
    db.session.delete(m)
    db.session.commit()
    flash(f'"{m.name}" deleted.')
    return redirect(url_for('monsters_bp.library'))


# ── Session monster instance controls (AJAX) ──────────────────────────────────

@monsters_bp.route('/instance/<int:monster_id>/hp', methods=['POST'])
@login_required
@dm_required
def instance_hp(monster_id):
    sm = tblSessionMonsters.query.get_or_404(monster_id)
    data = request.get_json()
    delta = int(data.get('delta', 0))
    sm.hp_current = max(0, min(sm.hp_max, sm.hp_current + delta))
    if sm.hp_current == 0:
        sm.is_alive = 0
    db.session.commit()
    return jsonify({'ok': True, 'hp_current': sm.hp_current, 'hp_pct': sm.hp_pct(),
                    'is_alive': sm.is_alive})


@monsters_bp.route('/instance/<int:monster_id>/hp-set', methods=['POST'])
@login_required
@dm_required
def instance_hp_set(monster_id):
    sm = tblSessionMonsters.query.get_or_404(monster_id)
    data = request.get_json()
    sm.hp_current = max(0, min(sm.hp_max, int(data.get('hp', sm.hp_current))))
    sm.is_alive = 0 if sm.hp_current == 0 else 1
    db.session.commit()
    return jsonify({'ok': True, 'hp_current': sm.hp_current, 'hp_pct': sm.hp_pct(),
                    'is_alive': sm.is_alive})


@monsters_bp.route('/instance/<int:monster_id>/initiative', methods=['POST'])
@login_required
@dm_required
def instance_initiative(monster_id):
    sm = tblSessionMonsters.query.get_or_404(monster_id)
    data = request.get_json()
    sm.initiative = int(data.get('initiative', 0))
    db.session.commit()
    return jsonify({'ok': True, 'initiative': sm.initiative})


@monsters_bp.route('/instance/<int:monster_id>/condition', methods=['POST'])
@login_required
@dm_required
def instance_condition(monster_id):
    sm = tblSessionMonsters.query.get_or_404(monster_id)
    data = request.get_json()
    condition = data.get('condition', '').strip()
    action = data.get('action', 'add')  # 'add' or 'remove'
    conds = json.loads(sm.conditions or '[]')
    if action == 'add' and condition and condition not in conds:
        conds.append(condition)
    elif action == 'remove' and condition in conds:
        conds.remove(condition)
    sm.conditions = json.dumps(conds)
    db.session.commit()
    return jsonify({'ok': True, 'conditions': conds})


@monsters_bp.route('/instance/<int:monster_id>/revive', methods=['POST'])
@login_required
@dm_required
def instance_revive(monster_id):
    sm = tblSessionMonsters.query.get_or_404(monster_id)
    sm.is_alive = 1
    sm.hp_current = sm.hp_max
    db.session.commit()
    return jsonify({'ok': True})


@monsters_bp.route('/instance/<int:monster_id>/delete', methods=['POST'])
@login_required
@dm_required
def instance_delete(monster_id):
    sm = tblSessionMonsters.query.get_or_404(monster_id)
    db.session.delete(sm)
    db.session.commit()
    return jsonify({'ok': True})
