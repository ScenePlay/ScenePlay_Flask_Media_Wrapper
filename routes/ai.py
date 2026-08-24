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
import runware
from routes.auth import dm_required

ai_bp = Blueprint('ai_bp', __name__, url_prefix='/ttrpg/ai')

_IMAGE_MIMES = {'png': 'image/png', 'jpg': 'image/jpeg', 'jpeg': 'image/jpeg',
                'gif': 'image/gif', 'webp': 'image/webp'}


def _err(msg, status=502):
    return jsonify({'ok': False, 'error': str(msg)}), status


def _image_provider():
    """'gemini' (default) or 'runware' — Utilities → AI Generation. Applies
    to IMAGE flows only; layouts (text) and Veo video always use Gemini."""
    try:
        from sql import appsettingGet
        p = (appsettingGet('image_provider', 'gemini') or 'gemini').strip().lower()
    except Exception:
        p = 'gemini'
    return p if p in ('gemini', 'runware') else 'gemini'


def _image_ready():
    return runware.configured() if _image_provider() == 'runware' else gemini.configured()


def _text_provider():
    """Who designs/traces floorplan LAYOUTS ('gemini' default | 'runware').
    Veo video is Gemini-only regardless."""
    try:
        from sql import appsettingGet
        p = (appsettingGet('text_provider', 'gemini') or 'gemini').strip().lower()
    except Exception:
        p = 'gemini'
    return p if p in ('gemini', 'runware') else 'gemini'


def _text_ready():
    return runware.configured() if _text_provider() == 'runware' else gemini.configured()


def _need_image_key():
    if _image_provider() == 'runware':
        return _err('No Runware API key configured — add one under '
                    'Utilities → AI Generation.', 400)
    return _need_key()


def _need_text_key():
    if _text_provider() == 'runware':
        return _err('No Runware API key configured — add one under '
                    'Utilities → AI Generation.', 400)
    return _need_key()


def _generate_image(prompt, override_model=None, image=None, mime=None, size=None,
                    negative=None):
    """Provider dispatch for every image flow: (raw, ext, model_label, note).
    `note` is a DM-facing heads-up (e.g. the Runware model has no image-input
    support, so the wall schematic was ignored) or None."""
    if _image_provider() == 'runware':
        model = runware.resolve_model()
        rw_info = {}
        raw, ext = runware.generate_image(prompt, model, image=image, mime=mime,
                                          size=size, info=rw_info, negative=negative)
        note = None
        if rw_info.get('seed_dropped'):
            note = (f'The Runware model {model} does not accept an input image, '
                    'so the wall schematic was ignored — the art follows the '
                    'prompt text only. Pick an image-to-image capable model in '
                    'Utilities → AI Generation for schematic-matched art.')
        return raw, ext, 'runware ' + model, note
    model = gemini.resolve_model('image', override_model)
    raw, ext = gemini.generate_image(prompt, model, image=image, mime=mime)
    return raw, ext, model, None


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
        'image_provider': _image_provider(),
        'image_ready': _image_ready(),
        'text_provider': _text_provider(),
        'text_ready': _text_ready(),
        'image_model': (runware.resolve_model() if _image_provider() == 'runware'
                        else gemini.resolve_model('image')),
        'text_model': (runware.resolve_text_model() if _text_provider() == 'runware'
                       else gemini.resolve_model('text')),
        'runware_configured': runware.configured(),
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
    if not _text_ready():
        return _need_text_key()
    d = request.get_json() or {}
    prompt = (d.get('prompt_text') or '').strip()
    if not prompt:
        return _err('Empty prompt.', 400)
    mode = d.get('mode') or 'design'
    image = mime = None
    if mode == 'trace':
        from models.ttrpg import tblBattleMaps
        bm = tblBattleMaps.query.get_or_404(int(d.get('map_id') or 0))
        got, reason = _map_bg_bytes(bm)
        if got is None:
            return _err(reason, 400)
        image, mime = got
    try:
        if _text_provider() == 'runware':
            model = runware.resolve_text_model()
            text = runware.generate_json(prompt, model, image=image, mime=mime)
            model = 'runware ' + model
        else:
            model = gemini.resolve_model('text', d.get('model'))
            text = gemini.generate_json(prompt, model, image=image, mime=mime)
    except (gemini.GeminiError, runware.RunwareError) as e:
        return _err(e)
    return jsonify({'ok': True, 'json_text': text, 'model': model})


@ai_bp.route('/map-art/<int:map_id>', methods=['POST'])
@login_required
@dm_required
def map_art(map_id):
    """Generate the map background image and return it for PREVIEW — the
    browser shows it (use / regenerate / discard) and saves the accepted one
    through the existing bg-paste endpoint, so nothing lands on the map the
    DM hasn't seen. When the browser sends the schematic blueprint PNG, it
    rides as the conditioning input image so the model paints directly over
    the floorplan geometry (the LAYOUT MATCH promise, enforced by pixels
    instead of prose)."""
    if not _image_ready():
        return _need_image_key()
    from models.ttrpg import tblBattleMaps
    bm = tblBattleMaps.query.get_or_404(map_id)
    d = request.get_json() or {}
    prompt = (d.get('prompt_text') or '').strip()
    if not prompt:
        return _err('Empty prompt.', 400)
    image = None
    if d.get('schematic_png_b64'):
        try:
            image = base64.b64decode(d['schematic_png_b64'])
        except Exception:
            return _err('Unreadable schematic image.', 400)
    if _image_provider() == 'runware' and not runware.instruction_native(
            runware.resolve_model()):
        # Diffusion models paint the words: the Gemini-style instruction
        # prompt ("reproduce the attached schematic...") comes back as a
        # schematic DIAGRAM. Send only the scene, caption-style — and turn
        # the white-background schematic into a dark textured seed the model
        # can paint over (a white seed returns a line drawing at ANY strength).
        # Gemini-family models on Runware (Nano Banana) skip both: they take
        # the instruction prompt and the raw schematic like Gemini direct.
        prompt = runware.distill_battlemap_prompt(prompt)
        if image:
            image = runware.prep_schematic_seed(image)
    try:
        raw, ext, model, note = _generate_image(
            prompt, d.get('model'), image=image, mime='image/png',
            size=runware.size_for_ratio(bm.grid_cols, bm.grid_rows),
            negative=runware.BATTLEMAP_NEGATIVE)
    except (gemini.GeminiError, runware.RunwareError) as e:
        return _err(e)
    return jsonify({'ok': True, 'ext': ext, 'model': model, 'map_id': bm.map_id,
                    'note': note,
                    'image_b64': base64.b64encode(raw).decode('ascii')})


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
    """Generate a seamless texture and return it for PREVIEW; the browser
    saves the accepted image through the library's paste endpoint (same
    validation as every other add). The name is validated HERE first so a
    bad or duplicate name fails before a generation is paid for."""
    if not _image_ready():
        return _need_image_key()
    d = request.get_json() or {}
    prompt = (d.get('prompt_text') or '').strip()
    if not prompt:
        return _err('Empty prompt.', 400)
    from routes.textures import _validate_texture_name
    name, name_err = _validate_texture_name({'name': d.get('name')})
    if name_err:
        return _err(name_err, 400)
    if _image_provider() == 'runware' and not runware.instruction_native(
            runware.resolve_model()):
        prompt = runware.distill_image_prompt(prompt)
    try:
        raw, ext, model, _note = _generate_image(prompt, d.get('model'))
    except (gemini.GeminiError, runware.RunwareError) as e:
        return _err(e)
    return jsonify({'ok': True, 'ext': ext, 'model': model, 'name': name,
                    'image_b64': base64.b64encode(raw).decode('ascii')})


@ai_bp.route('/image-generate', methods=['POST'])
@login_required
@dm_required
def image_generate():
    """Generic image generation (portraits, monster icons): returns the
    bytes to the browser, which saves them through the flow's own existing
    endpoint — zero new save paths."""
    if not _image_ready():
        return _need_image_key()
    d = request.get_json() or {}
    prompt = (d.get('prompt_text') or '').strip()
    if not prompt:
        return _err('Empty prompt.', 400)
    if _image_provider() == 'runware' and not runware.instruction_native(
            runware.resolve_model()):
        prompt = runware.distill_image_prompt(prompt)
    try:
        raw, ext, model, _note = _generate_image(prompt, d.get('model'))
    except (gemini.GeminiError, runware.RunwareError) as e:
        return _err(e)
    return jsonify({'ok': True, 'ext': ext, 'model': model,
                    'image_b64': base64.b64encode(raw).decode('ascii')})
