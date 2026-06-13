import json
import os
import uuid
from datetime import datetime, timezone

from flask import (Blueprint, render_template, redirect, url_for,
                   request, flash, jsonify, current_app)
from flask_login import login_required, current_user

from extensions import db, currentvolume
from models.ttrpg import (tblBattleMaps, tblBattleMapTokens, tblBattleMapEffects,
                           tblSessions, tblSessionParty,
                           tblSessionMonsters, tblCharacters)
from models.scenes import tblscenes
from routes.auth import dm_required
import relay_broadcaster

battlemap_bp = Blueprint('battlemap_bp', __name__, url_prefix='/ttrpg/battlemap')

UPLOAD_FOLDER = os.path.join('static', 'uploads', 'battlemaps')
ALLOWED_EXT   = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'mp4', 'webm', 'ogv'}
VIDEO_EXT     = {'mp4', 'webm', 'ogv'}
CELL_PX       = 64


def _now():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _token_relay_payload(t, bm):
    data = {
        'token_id':    t.token_id,
        'entity_type': t.entity_type,
        'entity_id':   t.entity_id,
        'col':         t.col,
        'row':         t.row,
        'x_pct':       t.col / max(1, bm.grid_cols - 1),
        'y_pct':       t.row / max(1, bm.grid_rows - 1),
        'label':       '',
        'token_type':  t.entity_type,
        'character_id': None,
        'image_url':   '',
    }
    if t.entity_type == 'player':
        char = db.session.get(tblCharacters, t.entity_id)
        if char:
            data['label']      = char.name
            data['character_id'] = t.entity_id
            data['hp_current'] = char.hp_current
            data['hp_max']     = char.hp_max
    elif t.entity_type == 'monster':
        sm = db.session.get(tblSessionMonsters, t.entity_id)
        if sm:
            data['label']      = sm.display_name
            data['hp_current'] = sm.hp_current
            data['hp_max']     = sm.hp_max
            data['conditions'] = json.loads(sm.conditions or '[]')
            try:
                raw = json.loads(sm.template.stats_json or '{}')
                if raw.get('image'):
                    data['image_url'] = 'https://www.dnd5eapi.co' + raw['image']
                # speed
                raw_spd = raw.get('speed', {})
                walk = raw_spd.get('walk', 0) if isinstance(raw_spd, dict) else 0
                if isinstance(walk, str):
                    walk = walk.replace(' ft.', '').strip()
                try:
                    walk = int(walk)
                except (ValueError, TypeError):
                    walk = 0
                data['speed'] = walk
                data['type']  = raw.get('type', '')
                data['ac']    = raw.get('armor_class', 0)
            except Exception:
                pass
    return data


def _push_map_state(bm):
    bg_url = (url_for('static', filename=f'uploads/battlemaps/{bm.bg_image}', _external=True)
              if bm.bg_image else '')
    effects = [{
        'effect_id':    e.effect_id,
        'shape':        e.shape,
        'label':        e.label or '',
        'anchor_x':     e.anchor_x,
        'anchor_y':     e.anchor_y,
        'size_ft':      e.size_ft,
        'angle':        e.angle,
        'fill_color':   e.fill_color,
        'fill_opacity': e.fill_opacity,
        'border_color': e.border_color,
    } for e in bm.effects]
    relay_broadcaster.broadcast_map_update(
        bg_url, bm.grid_cols, bm.grid_rows,
        [_token_relay_payload(t, bm) for t in bm.tokens],
        effects=effects,
    )


def _allowed(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXT


def _delete_bg_file(filename):
    if not filename:
        return
    path = os.path.join(current_app.root_path, UPLOAD_FOLDER, filename)
    if os.path.exists(path):
        os.remove(path)


# ── Active map redirect (players) ────────────────────────────────────────────

@battlemap_bp.route('/maps')
@login_required
@dm_required
def all_maps():
    sessions = (tblSessions.query
                .join(tblBattleMaps, tblBattleMaps.session_id == tblSessions.session_id)
                .order_by(tblSessions.created_at.desc())
                .distinct()
                .all())
    # Attach maps list to each session for easy template access
    for s in sessions:
        s._maps = (tblBattleMaps.query
                   .filter_by(session_id=s.session_id)
                   .order_by(tblBattleMaps.map_id)
                   .all())
    return render_template('ttrpg/maps_overview.html', sessions=sessions)


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

    _push_map_state(bm)

    # Stamp all tokens on the newly active map with the current time (ISO UTC).
    # relay_receiver uses this to detect which relay positions predate this activation
    # and must not overwrite the map's explicit token placements.
    activation_ts = datetime.now(timezone.utc).isoformat()
    for t in bm.tokens:
        t.updated_at = activation_ts
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


@battlemap_bp.route('/<int:map_id>/edit', methods=['POST'])
@login_required
@dm_required
def map_edit(map_id):
    bm = tblBattleMaps.query.get_or_404(map_id)
    name = request.form.get('name', '').strip()
    if name:
        bm.name = name
    cols = max(5, min(60, int(request.form.get('cols', bm.grid_cols) or bm.grid_cols)))
    rows = max(5, min(60, int(request.form.get('rows', bm.grid_rows) or bm.grid_rows)))
    bm.grid_cols = cols
    bm.grid_rows = rows
    # Clamp any tokens that would be outside the new grid
    for t in bm.tokens:
        changed = False
        if t.col >= cols:
            t.col = cols - 1
            changed = True
        if t.row >= rows:
            t.row = rows - 1
            changed = True
        if changed:
            t.updated_at = datetime.now(timezone.utc).isoformat()
    db.session.commit()
    _push_map_state(bm)
    flash(f'Map "{bm.name}" updated.')
    return redirect(url_for('battlemap_bp.session_maps', session_id=bm.session_id))


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
        _push_map_state(bm)
        flash('Background image updated.')
    return redirect(url_for('battlemap_bp.session_maps', session_id=bm.session_id))


@battlemap_bp.route('/<int:map_id>/bg-paste', methods=['POST'])
@login_required
@dm_required
def map_bg_paste(map_id):
    bm = tblBattleMaps.query.get_or_404(map_id)
    f = request.files.get('bg_image')
    if not f:
        return jsonify({'ok': False, 'error': 'no file'}), 400
    ext = (request.form.get('ext') or 'png').lower()
    if ext not in ALLOWED_EXT:
        ext = 'png'
    _delete_bg_file(bm.bg_image)
    folder = os.path.join(current_app.root_path, UPLOAD_FOLDER)
    os.makedirs(folder, exist_ok=True)
    filename = f'{uuid.uuid4().hex}.{ext}'
    f.save(os.path.join(folder, filename))
    bm.bg_image = filename
    db.session.commit()
    is_video = ext in VIDEO_EXT
    url = url_for('static', filename='uploads/battlemaps/' + filename)
    _push_map_state(bm)
    return jsonify({'ok': True, 'url': url, 'is_video': is_video, 'filename': filename})


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
    sess = db.session.get(tblSessions, bm.session_id)

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

    campaign_scenes = []
    if sess and sess.campaign_id:
        campaign_scenes = (tblscenes.query
                           .filter_by(campaign_id=sess.campaign_id, active=1)
                           .order_by(tblscenes.orderBy)
                           .all())

    try:
        current_vol = currentvolume()
    except Exception:
        current_vol = 50

    # Determine roller name: player's character name or DM display name
    roller_name = current_user.display_name
    if not current_user.is_dm():
        for sp in sess.party:
            if sp.character.user_id == current_user.user_id:
                roller_name = sp.character.name
                break

    if current_user.is_dm() and bm.is_active:
        _push_map_state(bm)

    return render_template('ttrpg/battlemap.html',
                           bm=bm, sess=sess,
                           monsters=monsters, party=party,
                           on_map_monster_ids=on_map_monster_ids,
                           on_map_player_ids=on_map_player_ids,
                           cell_px=CELL_PX,
                           roller_name=roller_name,
                           campaign_scenes=campaign_scenes,
                           current_vol=current_vol)


# ── Relay presence endpoint ──────────────────────────────────────────────────

@battlemap_bp.route('/relay-presence')
@login_required
def relay_presence():
    if not current_user.is_dm():
        from flask import abort
        abort(403)
    presence = relay_broadcaster.get_presence()
    return jsonify({'presence': presence})


# ── Relay roll feed proxy ─────────────────────────────────────────────────────

@battlemap_bp.route('/relay-rolls')
@login_required
@dm_required
def relay_rolls():
    since_id = request.args.get('since_id', 0, type=int)
    rolls = relay_broadcaster.get_relay_rolls(since_id)
    return jsonify({'rolls': rolls})


# ── State poll endpoint ───────────────────────────────────────────────────────

@battlemap_bp.route('/<int:map_id>/state')
@login_required
def map_state(map_id):
    bm     = tblBattleMaps.query.get_or_404(map_id)
    result = []

    for t in bm.tokens:
        if t.entity_type == 'monster':
            sm = db.session.get(tblSessionMonsters, t.entity_id)
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
            char = db.session.get(tblCharacters, t.entity_id)
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
                'user_id':     char.user_id,
            })

    effects = [{
        'effect_id':    e.effect_id,
        'shape':        e.shape,
        'label':        e.label,
        'anchor_x':     e.anchor_x,
        'anchor_y':     e.anchor_y,
        'size_ft':      e.size_ft,
        'angle':        e.angle,
        'fill_color':   e.fill_color,
        'fill_opacity': e.fill_opacity,
        'border_color': e.border_color,
    } for e in bm.effects]

    return jsonify({
        'tokens':    result,
        'effects':   effects,
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
        col=0, row=0, updated_at=datetime.now(timezone.utc).isoformat(),
    )
    db.session.add(t)
    db.session.commit()

    _push_map_state(bm)
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

    bm = db.session.get(tblBattleMaps, map_id)
    if bm:
        _push_map_state(bm)
    return jsonify({'ok': True})


@battlemap_bp.route('/<int:map_id>/token/move', methods=['POST'])
@login_required
def token_move(map_id):
    bm   = tblBattleMaps.query.get_or_404(map_id)
    data = request.get_json()
    t    = tblBattleMapTokens.query.get_or_404(data.get('token_id'))
    if t.map_id != map_id:
        return jsonify({'ok': False}), 403
    if not current_user.is_dm():
        if t.entity_type != 'player':
            return jsonify({'ok': False}), 403
        char = db.session.get(tblCharacters, t.entity_id)
        if not char or char.user_id != current_user.user_id:
            return jsonify({'ok': False}), 403
    t.col = max(0, min(bm.grid_cols - 1, int(data.get('col', t.col))))
    t.row = max(0, min(bm.grid_rows - 1, int(data.get('row', t.row))))
    t.updated_at = datetime.now(timezone.utc).isoformat()
    db.session.commit()

    label = ''
    character_id = None
    if t.entity_type == 'player':
        char = db.session.get(tblCharacters, t.entity_id)
        if char:
            label = char.name
            character_id = t.entity_id
    elif t.entity_type == 'monster':
        sm = db.session.get(tblSessionMonsters, t.entity_id)
        if sm:
            label = sm.display_name
    x_pct = t.col / max(1, bm.grid_cols - 1)
    y_pct = t.row / max(1, bm.grid_rows - 1)
    relay_broadcaster.broadcast_token_move(
        t.token_id, x_pct, y_pct,
        label=label, token_type=t.entity_type, character_id=character_id,
    )
    return jsonify({'ok': True, 'col': t.col, 'row': t.row})


# ── Effect CRUD ───────────────────────────────────────────────────────────────

@battlemap_bp.route('/<int:map_id>/effect/add', methods=['POST'])
@login_required
@dm_required
def effect_add(map_id):
    tblBattleMaps.query.get_or_404(map_id)
    data = request.get_json()
    shape = data.get('shape', 'circle')
    if shape not in ('circle', 'cone', 'line', 'square', 'cloud'):
        return jsonify({'ok': False, 'error': 'invalid shape'}), 400
    e = tblBattleMapEffects(
        map_id       = map_id,
        shape        = shape,
        label        = data.get('label', '').strip()[:40],
        anchor_x     = float(data.get('anchor_x', 0)),
        anchor_y     = float(data.get('anchor_y', 0)),
        size_ft      = max(5, int(data.get('size_ft', 20))),
        angle        = float(data.get('angle', 0)),
        fill_color   = data.get('fill_color', '#ff4400'),
        fill_opacity = max(0.05, min(1.0, float(data.get('fill_opacity', 0.35)))),
        border_color = data.get('border_color', '#ff8800'),
        created_at   = _now(),
    )
    db.session.add(e)
    db.session.commit()
    _push_map_state(tblBattleMaps.query.get(map_id))
    return jsonify({'ok': True, 'effect_id': e.effect_id})


@battlemap_bp.route('/<int:map_id>/effect/<int:effect_id>/update', methods=['POST'])
@login_required
@dm_required
def effect_update(map_id, effect_id):
    e = tblBattleMapEffects.query.get_or_404(effect_id)
    if e.map_id != map_id:
        return jsonify({'ok': False}), 403
    data = request.get_json()
    if 'anchor_x'     in data: e.anchor_x     = float(data['anchor_x'])
    if 'anchor_y'     in data: e.anchor_y     = float(data['anchor_y'])
    if 'angle'        in data: e.angle        = float(data['angle'])
    if 'size_ft'      in data: e.size_ft      = max(5, int(data['size_ft']))
    if 'fill_color'   in data: e.fill_color   = data['fill_color']
    if 'fill_opacity' in data: e.fill_opacity = max(0.05, min(1.0, float(data['fill_opacity'])))
    if 'border_color' in data: e.border_color = data['border_color']
    if 'label'        in data: e.label        = data['label'].strip()[:40]
    db.session.commit()
    _push_map_state(tblBattleMaps.query.get(map_id))
    return jsonify({'ok': True})


@battlemap_bp.route('/<int:map_id>/effect/<int:effect_id>/delete', methods=['POST'])
@login_required
@dm_required
def effect_delete(map_id, effect_id):
    e = tblBattleMapEffects.query.get_or_404(effect_id)
    if e.map_id != map_id:
        return jsonify({'ok': False}), 403
    db.session.delete(e)
    db.session.commit()
    _push_map_state(tblBattleMaps.query.get(map_id))
    return jsonify({'ok': True})


@battlemap_bp.route('/<int:map_id>/effect/clear', methods=['POST'])
@login_required
@dm_required
def effect_clear(map_id):
    tblBattleMaps.query.get_or_404(map_id)
    tblBattleMapEffects.query.filter_by(map_id=map_id).delete()
    db.session.commit()
    _push_map_state(tblBattleMaps.query.get(map_id))
    return jsonify({'ok': True})


@battlemap_bp.route('/monster-redirect/<int:monster_id>')
@login_required
@dm_required
def monster_redirect(monster_id):
    sm = tblSessionMonsters.query.get_or_404(monster_id)
    return redirect(url_for('monsters_bp.view', template_id=sm.template_id))
