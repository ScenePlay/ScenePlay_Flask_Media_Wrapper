import json
import os
import uuid
from datetime import datetime

from flask import (Blueprint, render_template, redirect, url_for,
                   request, flash, jsonify, current_app)
from flask_login import login_required, current_user

from extensions import db
from models.ttrpg import (tblBattleMaps, tblBattleMapTokens,
                           tblSessions, tblSessionParty,
                           tblSessionMonsters, tblCharacters)
from routes.auth import dm_required

battlemap_bp = Blueprint('battlemap_bp', __name__, url_prefix='/ttrpg/battlemap')

UPLOAD_FOLDER = os.path.join('static', 'uploads', 'battlemaps')
ALLOWED_EXT   = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
CELL_PX       = 64


def _now():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _allowed(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXT


def _delete_bg_file(filename):
    if not filename:
        return
    path = os.path.join(current_app.root_path, UPLOAD_FOLDER, filename)
    if os.path.exists(path):
        os.remove(path)


# ── Active map redirect (players) ────────────────────────────────────────────

@battlemap_bp.route('/active')
@login_required
def active_map():
    active_session = tblSessions.query.filter_by(status='active').first()
    if active_session:
        bm = tblBattleMaps.query.filter_by(
            session_id=active_session.session_id, is_active=1).first()
        if bm:
            return redirect(url_for('battlemap_bp.map_view', map_id=bm.map_id))
    flash('No active battle map right now.')
    return redirect(url_for('ttrpg.my_character'))


# ── Map manager (DM) ──────────────────────────────────────────────────────────

@battlemap_bp.route('/session/<int:session_id>')
@login_required
@dm_required
def session_maps(session_id):
    sess = tblSessions.query.get_or_404(session_id)
    maps = (tblBattleMaps.query
            .filter_by(session_id=session_id)
            .order_by(tblBattleMaps.map_id)
            .all())
    return render_template('ttrpg/battlemap_manage.html', sess=sess, maps=maps)


@battlemap_bp.route('/session/<int:session_id>/new', methods=['POST'])
@login_required
@dm_required
def map_new(session_id):
    tblSessions.query.get_or_404(session_id)
    name = request.form.get('name', '').strip() or 'Untitled Map'
    cols = max(5, min(60, int(request.form.get('cols', 20) or 20)))
    rows = max(5, min(60, int(request.form.get('rows', 20) or 20)))
    bm = tblBattleMaps(
        session_id=session_id, name=name,
        grid_cols=cols, grid_rows=rows,
        bg_image='', is_active=0, created_at=_now(),
    )
    db.session.add(bm)
    db.session.commit()
    flash(f'Map "{name}" created.')
    return redirect(url_for('battlemap_bp.session_maps', session_id=session_id))


@battlemap_bp.route('/<int:map_id>/activate', methods=['POST'])
@login_required
@dm_required
def map_activate(map_id):
    bm = tblBattleMaps.query.get_or_404(map_id)
    tblBattleMaps.query.filter_by(session_id=bm.session_id).update({'is_active': 0})
    bm.is_active = 1
    db.session.commit()
    flash(f'"{bm.name}" is now the active map.')
    return redirect(url_for('battlemap_bp.session_maps', session_id=bm.session_id))


@battlemap_bp.route('/<int:map_id>/delete', methods=['POST'])
@login_required
@dm_required
def map_delete(map_id):
    bm = tblBattleMaps.query.get_or_404(map_id)
    session_id = bm.session_id
    _delete_bg_file(bm.bg_image)
    db.session.delete(bm)
    db.session.commit()
    flash('Map deleted.')
    return redirect(url_for('battlemap_bp.session_maps', session_id=session_id))


@battlemap_bp.route('/<int:map_id>/bg', methods=['POST'])
@login_required
@dm_required
def map_bg(map_id):
    bm = tblBattleMaps.query.get_or_404(map_id)
    f = request.files.get('bg_image')
    if f and f.filename and _allowed(f.filename):
        _delete_bg_file(bm.bg_image)
        ext = f.filename.rsplit('.', 1)[1].lower()
        filename = f'{uuid.uuid4().hex}.{ext}'
        folder = os.path.join(current_app.root_path, UPLOAD_FOLDER)
        os.makedirs(folder, exist_ok=True)
        f.save(os.path.join(folder, filename))
        bm.bg_image = filename
        db.session.commit()
        flash('Background image updated.')
    return redirect(url_for('battlemap_bp.session_maps', session_id=bm.session_id))


@battlemap_bp.route('/<int:map_id>/bg/clear', methods=['POST'])
@login_required
@dm_required
def map_bg_clear(map_id):
    bm = tblBattleMaps.query.get_or_404(map_id)
    _delete_bg_file(bm.bg_image)
    bm.bg_image = ''
    db.session.commit()
    return redirect(url_for('battlemap_bp.session_maps', session_id=bm.session_id))


# ── Shared map view ───────────────────────────────────────────────────────────

@battlemap_bp.route('/<int:map_id>/view')
@login_required
def map_view(map_id):
    bm   = tblBattleMaps.query.get_or_404(map_id)
    sess = tblSessions.query.get(bm.session_id)

    monsters = []
    party    = []
    on_map_monster_ids = set()
    on_map_player_ids  = set()

    if current_user.is_dm():
        monsters = (tblSessionMonsters.query
                    .filter_by(session_id=bm.session_id, is_alive=1)
                    .order_by(tblSessionMonsters.sort_order)
                    .all())
        party = [sp.character for sp in sess.party]
        for t in bm.tokens:
            if t.entity_type == 'monster':
                on_map_monster_ids.add(t.entity_id)
            else:
                on_map_player_ids.add(t.entity_id)

    return render_template('ttrpg/battlemap.html',
                           bm=bm, sess=sess,
                           monsters=monsters, party=party,
                           on_map_monster_ids=on_map_monster_ids,
                           on_map_player_ids=on_map_player_ids,
                           cell_px=CELL_PX)


# ── State poll endpoint ───────────────────────────────────────────────────────

@battlemap_bp.route('/<int:map_id>/state')
@login_required
def map_state(map_id):
    bm     = tblBattleMaps.query.get_or_404(map_id)
    result = []

    for t in bm.tokens:
        if t.entity_type == 'monster':
            sm = tblSessionMonsters.query.get(t.entity_id)
            if not sm:
                continue
            raw  = json.loads(sm.template.stats_json or '{}')
            img  = ('https://www.dnd5eapi.co' + raw['image']) if raw.get('image') else ''
            raw_spd = raw.get('speed', {})
            walk = raw_spd.get('walk', 0) if isinstance(raw_spd, dict) else 0
            if isinstance(walk, str):
                walk = walk.replace(' ft.', '').strip()
            try:
                walk = int(walk)
            except (ValueError, TypeError):
                walk = 0
            result.append({
                'token_id':    t.token_id,
                'entity_type': 'monster',
                'entity_id':   t.entity_id,
                'name':        sm.display_name,
                'col':         t.col,
                'row':         t.row,
                'hp_current':  sm.hp_current,
                'hp_max':      sm.hp_max,
                'hp_pct':      sm.hp_pct(),
                'is_alive':    sm.is_alive,
                'image_url':   img,
                'color':       '#cc3333',
                'conditions':  json.loads(sm.conditions or '[]'),
                'skills':      [],
                'speed':       walk,
            })
        elif t.entity_type == 'player':
            char = tblCharacters.query.get(t.entity_id)
            if not char:
                continue
            img = (url_for('static', filename=f'uploads/portraits/{char.portrait_path}')
                   if char.portrait_path else '')
            result.append({
                'token_id':    t.token_id,
                'entity_type': 'player',
                'entity_id':   t.entity_id,
                'name':        char.name,
                'col':         t.col,
                'row':         t.row,
                'hp_current':  char.hp_current,
                'hp_max':      char.hp_max,
                'hp_pct':      char.hp_pct(),
                'is_alive':    1,
                'image_url':   img,
                'color':       '#4a9eff',
                'conditions':  [c.condition_name for c in char.conditions],
                'skills':      [{'name': s.skill_name, 'bonus': s.bonus, 'proficient': bool(s.proficient)}
                                for s in sorted(char.skills, key=lambda x: x.order_by)],
                'speed':       char.speed,
            })

    return jsonify({
        'tokens':    result,
        'grid_cols': bm.grid_cols,
        'grid_rows': bm.grid_rows,
    })


# ── Token CRUD ────────────────────────────────────────────────────────────────

@battlemap_bp.route('/<int:map_id>/token/add', methods=['POST'])
@login_required
@dm_required
def token_add(map_id):
    bm = tblBattleMaps.query.get_or_404(map_id)
    data        = request.get_json()
    entity_type = data.get('entity_type')
    entity_id   = int(data.get('entity_id', 0))

    if entity_type not in ('monster', 'player') or not entity_id:
        return jsonify({'ok': False, 'error': 'invalid entity'}), 400

    existing = tblBattleMapTokens.query.filter_by(
        map_id=map_id, entity_type=entity_type, entity_id=entity_id).first()
    if existing:
        return jsonify({'ok': False, 'error': 'already on map'})

    t = tblBattleMapTokens(
        map_id=map_id, entity_type=entity_type, entity_id=entity_id,
        col=0, row=0, updated_at=_now(),
    )
    db.session.add(t)
    db.session.commit()
    return jsonify({'ok': True, 'token_id': t.token_id})


@battlemap_bp.route('/<int:map_id>/token/remove', methods=['POST'])
@login_required
@dm_required
def token_remove(map_id):
    data = request.get_json()
    t    = tblBattleMapTokens.query.get_or_404(data.get('token_id'))
    if t.map_id != map_id:
        return jsonify({'ok': False}), 403
    db.session.delete(t)
    db.session.commit()
    return jsonify({'ok': True})


@battlemap_bp.route('/<int:map_id>/token/move', methods=['POST'])
@login_required
def token_move(map_id):
    bm   = tblBattleMaps.query.get_or_404(map_id)
    data = request.get_json()
    t    = tblBattleMapTokens.query.get_or_404(data.get('token_id'))
    if t.map_id != map_id:
        return jsonify({'ok': False}), 403
    t.col = max(0, min(bm.grid_cols - 1, int(data.get('col', t.col))))
    t.row = max(0, min(bm.grid_rows - 1, int(data.get('row', t.row))))
    t.updated_at = _now()
    db.session.commit()
    return jsonify({'ok': True, 'col': t.col, 'row': t.row})
