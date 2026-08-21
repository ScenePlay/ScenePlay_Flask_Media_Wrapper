"""One-click Gemini generation endpoints.

Bridges the browser-built prompts (the SAME prompt builders the copy-paste
flow uses) to the Gemini API and pipes results into the existing save paths:
floorplan JSON goes back to the browser for the preview-first pipeline (this
module never writes a floorplan), map art/video lands via battlemap's
_store_bg_bytes, textures via textures._add_texture. The API key never
leaves the server (see gemini.py).

All endpoints are DM-only. Errors come back as {ok: False, error: msg} with
a message safe to show at the table.
"""
import base64
import os

from flask import Blueprint, current_app, jsonify, request
from flask_login import login_required

import gemini
from routes.auth import dm_required

ai_bp = Blueprint('ai_bp', __name__, url_prefix='/ttrpg/ai')

_IMAGE_MIMES = {'png': 'image/png', 'jpg': 'image/jpeg', 'jpeg': 'image/jpeg',
                'gif': 'image/gif', 'webp': 'image/webp'}


def _err(msg, status=502):
    return jsonify({'ok': False, 'error': str(msg)}), status


def _need_key():
    return _err('No Gemini API key configured — add one under '
                'Utilities → Gemini AI.', 400)


@ai_bp.route('/status')
@login_required
@dm_required
def status():
    """UI gate for the ✨ buttons. Never includes the key itself."""
    return jsonify({
        'ok': True,
        'configured': gemini.configured(),
        'key_source': gemini.key_source(),
        'models': {m: gemini.resolve_model(m) for m in ('text', 'image', 'video')},
        'choices': {'text': list(gemini.TEXT_MODELS),
                    'image': list(gemini.IMAGE_MODELS),
                    'video': list(gemini.VIDEO_MODELS)},
    })


def _map_bg_bytes(bm):
    """(bytes, mime) of a map's still background, or (None, reason)."""
    if not bm.bg_image:
        return None, 'This map has no background image yet.'
    ext = bm.bg_image.rsplit('.', 1)[-1].lower()
    from routes.battlemap import UPLOAD_FOLDER, VIDEO_EXT
    if ext in VIDEO_EXT:
        return None, ('This map has a VIDEO background — tracing needs a '
                      'still image. Use the copy-paste flow with a '
                      'screenshot of one frame instead.')
    path = os.path.join(current_app.root_path, UPLOAD_FOLDER, bm.bg_image)
    if not os.path.isfile(path):
        return None, 'The background image file is missing on disk.'
    with open(path, 'rb') as f:
        return (f.read(), _IMAGE_MIMES.get(ext, 'image/png')), None


@ai_bp.route('/floorplan-generate', methods=['POST'])
@login_required
@dm_required
def floorplan_generate():
    """Design or trace a floorplan. Returns the raw JSON text for the
    browser's paste box + preview pipeline — deliberately NO server-side
    save: validation, doorway carve, floor strip and the DM's confirm all
    stay in one place."""
    if not gemini.configured():
        return _need_key()
    d = request.get_json() or {}
    prompt = (d.get('prompt_text') or '').strip()
    if not prompt:
        return _err('Empty prompt.', 400)
    mode = d.get('mode') or 'design'
    model = gemini.resolve_model('text', d.get('model'))
    image = mime = None
    if mode == 'trace':
        from models.ttrpg import tblBattleMaps
        bm = tblBattleMaps.query.get_or_404(int(d.get('map_id') or 0))
        got, reason = _map_bg_bytes(bm)
        if got is None:
            return _err(reason, 400)
        image, mime = got
    try:
        text = gemini.generate_json(prompt, model, image=image, mime=mime)
    except gemini.GeminiError as e:
        return _err(e)
    return jsonify({'ok': True, 'json_text': text, 'model': model})


@ai_bp.route('/map-art/<int:map_id>', methods=['POST'])
@login_required
@dm_required
def map_art(map_id):
    """Generate the map background image. When the browser sends the
    schematic blueprint PNG, it rides as the conditioning input image so the
    model paints directly over the floorplan geometry (the LAYOUT MATCH
    promise, enforced by pixels instead of prose)."""
    if not gemini.configured():
        return _need_key()
    from models.ttrpg import tblBattleMaps
    bm = tblBattleMaps.query.get_or_404(map_id)
    d = request.get_json() or {}
    prompt = (d.get('prompt_text') or '').strip()
    if not prompt:
        return _err('Empty prompt.', 400)
    model = gemini.resolve_model('image', d.get('model'))
    image = None
    if d.get('schematic_png_b64'):
        try:
            image = base64.b64decode(d['schematic_png_b64'])
        except Exception:
            return _err('Unreadable schematic image.', 400)
    try:
        raw, ext = gemini.generate_image(prompt, model, image=image,
                                         mime='image/png')
    except gemini.GeminiError as e:
        return _err(e)
    from routes.battlemap import _store_bg_bytes
    payload = _store_bg_bytes(bm, raw, ext)
    payload['model'] = model
    return jsonify(payload)


@ai_bp.route('/map-video/<int:map_id>', methods=['POST'])
@login_required
@dm_required
def map_video(map_id):
    """Start a Veo job animating this map. The current still background (if
    any) becomes the starting frame — 'bring this painting to life'. Returns
    a job id; the browser polls /job/<id>."""
    if not gemini.configured():
        return _need_key()
    from models.ttrpg import tblBattleMaps
    bm = tblBattleMaps.query.get_or_404(map_id)
    d = request.get_json() or {}
    prompt = (d.get('prompt_text') or '').strip()
    if not prompt:
        return _err('Empty prompt.', 400)
    model = gemini.resolve_model('video', d.get('model'))
    got, _reason = _map_bg_bytes(bm)   # missing/video bg → pure text-to-video
    image, mime = got if got else (None, None)

    app = current_app._get_current_object()

    def _save(raw, ext):
        # Worker thread: needs its own app context for the DB commit + push.
        with app.app_context():
            from extensions import db
            from models.ttrpg import tblBattleMaps as _maps
            from routes.battlemap import _store_bg_bytes
            live = db.session.get(_maps, map_id)
            if live is None:
                raise RuntimeError('map was deleted while generating')
            return _store_bg_bytes(live, raw, ext)

    job_id = gemini.start_video_job(prompt, model, image=image, mime=mime,
                                    on_success=_save)
    return jsonify({'ok': True, 'job_id': job_id, 'model': model})


@ai_bp.route('/job/<job_id>')
@login_required
@dm_required
def job(job_id):
    rec = gemini.job_status(job_id)
    if rec is None:
        return _err('Unknown job — the server may have restarted. '
                    'Start the generation again.', 404)
    return jsonify({'ok': True, 'status': rec['status'],
                    'error': rec['error'], 'result': rec['result']})


@ai_bp.route('/texture-generate', methods=['POST'])
@login_required
@dm_required
def texture_generate():
    """Generate a seamless texture and add it straight to the library —
    same validation as the paste path (slug rules, name collisions...)."""
    if not gemini.configured():
        return _need_key()
    d = request.get_json() or {}
    prompt = (d.get('prompt_text') or '').strip()
    if not prompt:
        return _err('Empty prompt.', 400)
    model = gemini.resolve_model('image', d.get('model'))
    try:
        raw, ext = gemini.generate_image(prompt, model)
    except gemini.GeminiError as e:
        return _err(e)
    from routes.textures import _add_texture
    payload, status_code = _add_texture(raw, ext, {
        'name': d.get('name'), 'category': d.get('category'),
        'tile_ft': d.get('tile_ft'), 'source': 'ai',
    })
    return jsonify(payload), status_code


@ai_bp.route('/image-generate', methods=['POST'])
@login_required
@dm_required
def image_generate():
    """Generic image generation (portraits, monster icons): returns the
    bytes to the browser, which saves them through the flow's own existing
    endpoint — zero new save paths."""
    if not gemini.configured():
        return _need_key()
    d = request.get_json() or {}
    prompt = (d.get('prompt_text') or '').strip()
    if not prompt:
        return _err('Empty prompt.', 400)
    model = gemini.resolve_model('image', d.get('model'))
    try:
        raw, ext = gemini.generate_image(prompt, model)
    except gemini.GeminiError as e:
        return _err(e)
    return jsonify({'ok': True, 'ext': ext, 'model': model,
                    'image_b64': base64.b64encode(raw).decode('ascii')})
