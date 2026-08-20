"""3D texture library endpoints.

One unified library from two sources:
  - built-in: repo files under static/textures/builtin/ + manifest.json
    (CC0 starter set, never deletable)
  - user-added: rows in tblTextures + files under static/uploads/textures/
    (AI prompt paste-backs and uploads)

The /manifest endpoint serves the union; floorplan JSON references textures
by slug `name`. Reads are login_required (players' 3D viewers resolve
textures too); writes are DM-only, mirroring routes/battlemap.py.
"""
import json
import os
import re

from flask import Blueprint, current_app, jsonify, request, url_for
from flask_login import login_required

from extensions import db
from models.ttrpg import tblTextures
from routes._util import _now
from routes.auth import dm_required

textures_bp = Blueprint('textures_bp', __name__, url_prefix='/ttrpg/textures')

UPLOAD_FOLDER = os.path.join('static', 'uploads', 'textures')
BUILTIN_FOLDER = os.path.join('static', 'textures', 'builtin')

SLUG_RE = re.compile(r'^[a-z0-9_-]{1,64}$')
CATEGORIES = ('stone', 'brick', 'wood', 'floor', 'plaster', 'metal',
              'ground', 'other')
TILE_FT_RANGE = (1.0, 50.0)
# Tiling surface detail: 1024px on a ~5 ft tile is plenty at eye level and
# keeps the relay push (which re-encodes smaller still) cheap.
MAX_TEXTURE_DIM = 1024


def _builtin_manifest():
    """The repo starter set, or [] when the folder is missing (fresh trees
    before assets sync, tests)."""
    path = os.path.join(current_app.root_path, BUILTIN_FOLDER, 'manifest.json')
    try:
        with open(path, encoding='utf-8') as f:
            entries = json.load(f)
    except (OSError, ValueError):
        return []
    out = []
    for e in entries:
        name = str(e.get('name', ''))
        if not SLUG_RE.match(name):
            continue
        out.append({
            'name': name,
            'category': str(e.get('category', 'other')),
            'tile_ft': float(e.get('tile_ft', 5)),
            'tags': str(e.get('tags', '')),
            'source': 'builtin',
            'url': url_for('static', filename=f'textures/builtin/{name}.jpg'),
        })
    return out


def _db_manifest():
    out = []
    for t in tblTextures.query.order_by(tblTextures.category,
                                        tblTextures.name).all():
        out.append({
            'name': t.name,
            'category': t.category,
            'tile_ft': t.tile_ft,
            'tags': '',
            'source': t.source,
            'url': url_for('static', filename=f'uploads/textures/{t.filename}'),
        })
    return out


def texture_manifest():
    """Union of builtin + user textures (builtin wins name collisions —
    uploads are blocked from taking builtin names, so a clash means a
    builtin was added later; the shipped file is the stable one)."""
    seen = set()
    out = []
    for entry in _builtin_manifest() + _db_manifest():
        if entry['name'] in seen:
            continue
        seen.add(entry['name'])
        out.append(entry)
    return out


def texture_names():
    """Just the referenceable slugs, for prompt catalogs and validation."""
    return [e['name'] for e in texture_manifest()]


def texture_paths(names):
    """{name: {'path': abs_file_path, 'tile_ft': f}} for the given slugs —
    the relay broadcaster embeds these files for remote 3D viewers."""
    out = {}
    wanted = set(names)
    if not wanted:
        return out
    builtin_dir = os.path.join(current_app.root_path, BUILTIN_FOLDER)
    for e in _builtin_manifest():
        if e['name'] in wanted:
            out[e['name']] = {'path': os.path.join(builtin_dir, e['name'] + '.jpg'),
                              'tile_ft': e['tile_ft']}
    upload_dir = os.path.join(current_app.root_path, UPLOAD_FOLDER)
    for t in tblTextures.query.filter(tblTextures.name.in_(wanted)).all():
        out.setdefault(t.name, {'path': os.path.join(upload_dir, t.filename),
                                'tile_ft': t.tile_ft})
    return out


@textures_bp.route('/manifest')
@login_required
def manifest():
    return jsonify({'ok': True, 'textures': texture_manifest()})


def _existing_names():
    names = {e['name'] for e in _builtin_manifest()}
    names.update(t.name for t in tblTextures.query.all())
    return names


def _save_texture_image(raw, orig_ext):
    """Downscale to MAX_TEXTURE_DIM and save under a uuid filename.
    Returns the filename."""
    import uuid
    from relay_broadcaster import _downscale_image
    out, ext = _downscale_image(raw, orig_ext, MAX_TEXTURE_DIM)
    dest = os.path.join(current_app.root_path, UPLOAD_FOLDER)
    os.makedirs(dest, exist_ok=True)
    filename = f'{uuid.uuid4().hex}.{ext}'
    with open(os.path.join(dest, filename), 'wb') as f:
        f.write(out)
    return filename


def _add_texture(raw, orig_ext, form):
    """Shared by upload and clipboard paste. Returns (payload, status)."""
    name = str(form.get('name', '')).strip().lower().replace(' ', '_')
    if not SLUG_RE.match(name):
        return {'ok': False, 'error': 'name must be 1-64 chars: a-z 0-9 _ -'}, 400
    if name in _existing_names():
        return {'ok': False, 'error': f'a texture named "{name}" already exists'}, 400
    category = str(form.get('category', 'other')).strip().lower()
    if category not in CATEGORIES:
        category = 'other'
    try:
        tile_ft = float(form.get('tile_ft', 5) or 5)
    except (TypeError, ValueError):
        tile_ft = 5.0
    tile_ft = max(TILE_FT_RANGE[0], min(TILE_FT_RANGE[1], tile_ft))
    source = 'ai' if form.get('source') == 'ai' else 'upload'
    if not raw:
        return {'ok': False, 'error': 'empty image'}, 400
    filename = _save_texture_image(raw, orig_ext)
    row = tblTextures(name=name, category=category, source=source,
                      filename=filename, tile_ft=tile_ft, created_at=_now())
    db.session.add(row)
    db.session.commit()
    return {'ok': True, 'name': name,
            'url': url_for('static', filename=f'uploads/textures/{filename}')}, 200


@textures_bp.route('/upload', methods=['POST'])
@login_required
@dm_required
def upload():
    f = request.files.get('image')
    if f is None or not f.filename:
        return jsonify({'ok': False, 'error': 'no image file'}), 400
    ext = (f.filename.rsplit('.', 1)[-1].lower()
           if '.' in f.filename else 'png')
    payload, status = _add_texture(f.read(), ext, request.form)
    return jsonify(payload), status


@textures_bp.route('/paste', methods=['POST'])
@login_required
@dm_required
def paste():
    """Clipboard flow (the AI-generate tab): raw image bytes in 'image',
    metadata in the form — same contract as battlemap bg-paste."""
    f = request.files.get('image')
    if f is None:
        return jsonify({'ok': False, 'error': 'no image data'}), 400
    ext = str(request.form.get('ext', 'png')).lower()
    if ext not in ('png', 'jpg', 'jpeg', 'webp'):
        ext = 'png'
    payload, status = _add_texture(f.read(), ext, request.form)
    return jsonify(payload), status


@textures_bp.route('/<name>/delete', methods=['POST'])
@login_required
@dm_required
def delete(name):
    row = tblTextures.query.filter_by(name=name).first()
    if row is None:
        # builtin names land here too — they have no DB row and never delete
        return jsonify({'ok': False, 'error': 'not a deletable texture'}), 404
    path = os.path.join(current_app.root_path, UPLOAD_FOLDER, row.filename)
    try:
        if os.path.isfile(path):
            os.remove(path)
    except OSError:
        pass
    db.session.delete(row)
    db.session.commit()
    return jsonify({'ok': True})
