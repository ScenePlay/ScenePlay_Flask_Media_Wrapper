"""Runware.ai image-generation client — the optional alternative to Gemini
for the IMAGE flows (map art, textures, portraits, monster icons). Text/JSON
layouts and Veo video always use Gemini; Runware only paints pictures.

Same design rules as gemini.py:
  - The API key lives ONLY in instance/runware_api_key (chmod 0600) or the
    RUNWARE_API_KEY env var — never in the database, backups, git, templates,
    or any URL.
  - Plain `requests` against the REST endpoint, auth via the Authorization
    Bearer HEADER.
  - Explicit timeouts; every failure normalizes into RunwareError with a
    message fit to show the DM.
  - No Flask imports — testable standalone.

API shape (https://runware.ai/docs): POST https://api.runware.ai/v1 with a
JSON ARRAY of task objects; an imageInference task carries taskUUID,
positivePrompt, model (an AIR id like runware:101@1 = FLUX.1 Dev),
width/height, and outputType base64Data returns imageBase64Data in
data[0]. Image-to-image conditioning is seedImage (data URI) + strength.
Errors arrive in an `errors` array with per-entry `message`.
"""
import base64
import io
import os
import uuid

import requests

API_URL = 'https://api.runware.ai/v1'
CHAT_URL = 'https://api.runware.ai/v1/chat/completions'   # OpenAI-compatible LLM endpoint

_KEY_PATH = os.path.join(os.path.dirname(os.path.realpath(__file__)),
                         'instance', 'runware_api_key')

# FLUX.1 Dev — the quality default; runware:100@1 (FLUX.1 Schnell) is the
# fast/cheap one. Free-text setting: any Runware/CivitAI AIR id is allowed
# (a bad id fails loudly with Runware's own error, never silently).
DEFAULT_MODEL = 'runware:101@1'
MODEL_SETTING = 'runware_model'
# Text (the schematic/layout designer). Runware hosts closed and open LLMs
# behind the same key; the chat endpoint uses SLUG ids (GET /v1/models lists
# them), not the AIR ids the image tasks use. Gemini via Runware is the
# default for layout quality.
DEFAULT_TEXT_MODEL = 'google-gemini-3-5-flash'
TEXT_MODEL_SETTING = 'runware_text_model'
PROMPT_MAX = 2900          # Runware caps positivePrompt length
SEED_STRENGTH = 0.8        # repaint hard but keep the seed image's layout

# Diffusion models (FLUX & friends) BOTH follow and literally PAINT prompt
# text — ScenePlay's instruction-style prompts came back with captions and
# descriptions rendered onto the image. Every Runware call therefore gets an
# explicit no-text clause appended and a negative prompt; Gemini's flows are
# untouched (it handles instruction prompts natively).
NO_TEXT_SUFFIX = (' Pure artwork only: absolutely no text, no words, no'
                  ' letters, no labels, no captions, no title, no watermark,'
                  ' no signature, no borders, no user interface elements.')
NEGATIVE_PROMPT = ('text, words, letters, typography, writing, labels,'
                   ' captions, title, description, watermark, signature,'
                   ' logo, user interface, borders, frame, split image,'
                   ' collage')
# Battle maps must sit flat under a square grid — diffusion models love to
# drift isometric, so the map flow adds these to the negative prompt.
BATTLEMAP_NEGATIVE = ('isometric, oblique angle, perspective view, 3d render,'
                      ' horizon, sky, walls seen from the side, tilted camera')


# The battle-map ART prompt is written FOR GEMINI: it instructs ("reproduce
# the attached schematic", "LAYOUT MATCH", wall-by-wall coordinates). A
# diffusion model paints what the words describe, so that prompt yields a
# schematic DIAGRAM instead of map art. distill_battlemap_prompt() keeps only
# the scene facts the page's builder writes as 'Label: value' lines and
# rebuilds them as a caption a diffusion model understands.
_SCENE_LABELS = ('Setting', 'Environment', 'Map type', 'Time of day',
                 'Atmosphere', 'Lighting', 'Art style', 'Additional details')


def distill_battlemap_prompt(prompt):
    import re
    text = prompt or ''
    bits = []
    for label in _SCENE_LABELS:
        m = re.search(r'^' + re.escape(label) + r': *(.+)$', text, re.M)
        if m:
            bits.append(m.group(1).strip().rstrip('.'))
    travel = 'TRAVEL MAP' in text
    if travel:
        head = ('hand-drawn fantasy cartography, top-down overland travel map '
                'for a tabletop RPG')
        tail = 'parchment tones, inked terrain, painterly, richly detailed'
    else:
        head = ('flat top-down orthographic battle map for a tabletop RPG, '
                'hand-painted game art, camera directly overhead pointing '
                'straight down, floor plan view, zero perspective')
        tail = ('richly detailed floor and terrain textures, dramatic '
                'lighting, no grid lines')
    return ', '.join([head] + bits + [tail])


_FACT_LABELS = ('Type', 'Setting', 'Description', 'Details', 'Environment',
                'Map type', 'Time of day', 'Atmosphere', 'Lighting',
                'Art style', 'Additional details')


def distill_image_prompt(prompt):
    """ScenePlay's ✨ prompts are INSTRUCTION DOCUMENTS written for Gemini
    ("## SUBJECT / ## REQUIREMENTS (CRITICAL) / bullet rules"). Diffusion
    models paint the document instead of following it. This rebuilds any of
    them as a caption: a framing head chosen from the document's first line,
    the 'Label: value' facts (minus Name — proper nouns invite rendered
    text), and the ART DIRECTION bullets. A prompt without '##' sections is
    already caption-ish and passes through untouched."""
    import re
    text = prompt or ''
    if '## ' not in text:
        return text
    low = text.lower()
    if 'battlemap' in low or 'battle map' in low or 'travel map' in low:
        return distill_battlemap_prompt(text)
    if 'seamlessly tileable' in low or 'material texture' in low:
        head = ('seamless tileable texture, flat material surface photographed '
                'perfectly straight-on, even diffuse lighting, no shadows, '
                'uniform repeating pattern filling the whole frame')
    elif 'top-down' in low and 'token' in low:
        head = ('top-down game token art, a single subject seen from directly '
                'above, centered, filling the frame, plain solid dark '
                'background, soft shadow directly beneath')
    elif 'token' in low or 'portrait' in low:
        head = ('fantasy character portrait for a game token, a single '
                'creature centered with head and upper body prominent, strong '
                'silhouette, plain softly darkened background')
    else:
        head = 'detailed digital illustration'
    bits = []
    for label in _FACT_LABELS:
        m = re.search(r'^' + re.escape(label) + r': *(.+)$', text, re.M)
        if m:
            bits.append(m.group(1).strip().rstrip('.'))
    m = re.search(r'^## ART DIRECTION\s*\n((?:- .*\n?)+)', text, re.M)
    art = []
    if m:
        art = [ln[2:].strip().rstrip('.') for ln in m.group(1).splitlines()
               if ln.startswith('- ')]
    return ', '.join([head] + bits + art)


def prep_schematic_seed(image_bytes):
    """The page's wall schematic is BLACK LINES ON WHITE — as an img2img
    seed its white background dominates the tonality and every strength
    setting returns a line drawing with decorations (verified against
    FLUX Dev). Re-render it as a seed a diffusion model can paint over:
    a dark noisy stone-floor base with the walls as lighter strokes. The
    geometry survives; the tonality invites real art. Returns the original
    bytes untouched if Pillow is unavailable or the image is unreadable."""
    try:
        from PIL import Image, ImageFilter
        src = Image.open(io.BytesIO(image_bytes))
        if src.mode in ('RGBA', 'LA', 'P'):
            base = Image.new('RGB', src.size, 'white')
            base.paste(src.convert('RGBA'), mask=src.convert('RGBA').split()[-1])
            src = base
        g = src.convert('L')
        # murky floor: gaussian noise squeezed into a dark band
        floor = Image.effect_noise(g.size, 40).point(
            lambda v: 38 + int(v * 26 / 255)).filter(ImageFilter.GaussianBlur(1.2))
        walls_mask = g.point(lambda v: 255 if v < 128 else 0)
        walls_mask = walls_mask.filter(ImageFilter.MaxFilter(5))   # thicken strokes
        lighter = Image.new('L', g.size, 150)
        out = Image.composite(lighter, floor, walls_mask).convert('RGB')
        buf = io.BytesIO()
        out.save(buf, 'PNG')
        return buf.getvalue()
    except Exception:
        return image_bytes


class RunwareError(Exception):
    """Raised for any Runware failure; str(e) is safe to show the DM."""


# ── API key management (mirrors gemini.py) ──────────────────────────────────

def load_api_key():
    env = (os.environ.get('RUNWARE_API_KEY') or '').strip()
    if env:
        return env
    try:
        with open(_KEY_PATH, encoding='utf-8') as f:
            key = f.read().strip()
            return key or None
    except OSError:
        return None


def save_api_key(key):
    key = (key or '').strip()
    if not key:
        return
    os.makedirs(os.path.dirname(_KEY_PATH), exist_ok=True)
    with open(_KEY_PATH, 'w', encoding='utf-8') as f:
        f.write(key)
    try:
        os.chmod(_KEY_PATH, 0o600)
    except OSError:
        pass


def clear_api_key():
    try:
        os.remove(_KEY_PATH)
    except OSError:
        pass


def configured():
    return load_api_key() is not None


def key_source():
    """'env' | 'file' | None — for the settings UI badge (never the key)."""
    if (os.environ.get('RUNWARE_API_KEY') or '').strip():
        return 'env'
    return 'file' if configured() else None


# ── model / size selection ──────────────────────────────────────────────────

def resolve_model(override=None):
    """Per-call override > the appsetting > the built-in default. An AIR id
    always contains ':'; anything without one is ignored."""
    candidates = [override]
    try:
        from sql import appsettingGet
        candidates.append(appsettingGet(MODEL_SETTING, ''))
    except Exception:
        pass
    for cand in candidates:
        cand = (cand or '').strip()
        if cand and ':' in cand:
            return cand
    return DEFAULT_MODEL


def list_text_models(timeout=(10, 30)):
    """The slug ids the chat endpoint accepts (GET /v1/models), or [] when
    the list cannot be fetched (no key, network) — advisory only."""
    key = load_api_key()
    if not key:
        return []
    try:
        resp = requests.get(API_URL + '/models', timeout=timeout,
                            headers={'Authorization': f'Bearer {key}'})
        return [m.get('id') for m in (resp.json().get('data') or []) if m.get('id')]
    except Exception:
        return []


def normalize_text_model(value):
    """(slug, error) for a value typed into the LAYOUT model field. The chat
    endpoint wants slugs (google-gemini-3-6-flash) but the rest of Runware
    uses AIR ids (google:gemini@3.6-flash) — an AIR form is converted and
    checked against the live model list. Unknown values fail with the
    closest matches; an unreachable list accepts the value as-is."""
    value = (value or '').strip()
    if not value or ' ' in value:
        return None, 'Enter a model id (no spaces).'
    ids = list_text_models()
    if not ids:
        return value, None                      # cannot verify — let the API decide
    if value in ids:
        return value, None
    converted = value.replace(':', '-').replace('@', '-').replace('.', '-')
    if converted in ids:
        return converted, None
    near = [i for i in ids if converted.split('-')[0] in i][:4] or ids[:4]
    return None, (f'"{value}" is not a Runware text model. Close matches: '
                  + ', '.join(near)
                  + '. (Layout models use slug ids like google-gemini-3-6-flash.)')


def resolve_text_model(override=None):
    """Like resolve_model, for the LLM used by the layout designer. Text
    slugs look like google-gemini-3-5-flash (the AIR colon form is also
    tolerated in case Runware unifies them)."""
    candidates = [override]
    try:
        from sql import appsettingGet
        candidates.append(appsettingGet(TEXT_MODEL_SETTING, ''))
    except Exception:
        pass
    for cand in candidates:
        cand = (cand or '').strip()
        if cand and ' ' not in cand and ('-' in cand or ':' in cand):
            return cand
    return DEFAULT_TEXT_MODEL


def generate_json(prompt, model=None, image=None, mime=None, timeout=(10, 240)):
    """The floorplan design/trace flow: prompt (optionally with the map image
    for vision models) -> the model's raw text reply, expected to be JSON.
    Uses Runware's OpenAI-compatible chat endpoint; no response_format is
    forced (not every hosted model supports JSON mode) — the prompts demand
    raw JSON and the page's paste pipeline strips code fences anyway."""
    key = load_api_key()
    if not key:
        raise RunwareError('No Runware API key configured — add one under '
                           'Utilities → AI Generation.')
    content = [{'type': 'text', 'text': prompt or ''}]
    if image:
        content.append({'type': 'image_url', 'image_url': {
            'url': 'data:%s;base64,' % (mime or 'image/png')
                   + base64.b64encode(image).decode('ascii')}})
    body = {'model': model or resolve_text_model(),
            'messages': [{'role': 'user', 'content': content}],
            'max_completion_tokens': 16000}
    try:
        resp = requests.post(CHAT_URL, json=body, timeout=timeout,
                             headers={'Authorization': f'Bearer {key}',
                                      'Content-Type': 'application/json'})
    except requests.RequestException as exc:
        raise RunwareError(f'Runware request failed: {exc}') from exc
    try:
        data = resp.json()
    except ValueError:
        raise RunwareError(f'Runware returned HTTP {resp.status_code} with an '
                           'unreadable body.')
    if isinstance(data, dict) and data.get('error'):
        e = data['error']
        msg = e.get('message') if isinstance(e, dict) else str(e)
        raise RunwareError(_friendly(resp.status_code, msg))
    if not resp.ok:
        raise RunwareError(f'Runware returned HTTP {resp.status_code}.')
    try:
        text = (data['choices'][0]['message']['content'] or '').strip()
    except (KeyError, IndexError, TypeError):
        raise RunwareError('Runware returned an unexpected reply shape.')
    if not text:
        raise RunwareError('Runware returned an empty reply.')
    return text


def lookup_model(air, timeout=(10, 30)):
    """The catalog entry for an AIR id via modelSearch, or None when it does
    not exist. Raises RunwareError only for auth problems; network/API
    hiccups return None-ish silently (lookups are advisory)."""
    key = load_api_key()
    if not key:
        return None
    try:
        resp = requests.post(
            API_URL, timeout=timeout,
            json=[{'taskType': 'modelSearch', 'taskUUID': str(uuid.uuid4()),
                   'search': air, 'limit': 10}],
            headers={'Authorization': f'Bearer {key}'})
        data = resp.json()
        results = (data.get('data') or [{}])[0].get('results', []) or []
    except Exception:
        return None
    for m in results:
        if m.get('air') == air:
            return m
    return None


def validate_image_model(air):
    """(ok, message) for a value typed into the IMAGE model field. Catches
    the classes of mistake the API only reports at generation time: an id
    that is not in the catalog, or one that is a text/video/audio model or
    a lora/embedding rather than an image checkpoint. Advisory: if the
    catalog cannot be checked (no key, network), the value passes."""
    m = lookup_model(air)
    if m is None:
        return True, None            # unknown OR unreachable — let the API decide
    cat = (m.get('category') or '').lower()
    if cat in ('checkpoint', ''):
        return True, None
    kind = {'text': 'a TEXT model', 'video': 'a VIDEO model',
            'audio': 'an AUDIO model', 'lora': 'a LoRA (an add-on, not a full model)',
            'embeddings': 'an embedding', 'controlnet': 'a ControlNet',
            'vae': 'a VAE', 'lycoris': 'a LyCORIS add-on'}.get(cat, f"a '{cat}' model")
    return False, (f'"{air}" is {kind} — it cannot generate images. '
                   f'For Google image models on Runware use google:4@3 '
                   f'(Nano Banana 2 / Gemini 3.1 Flash Image).')


def _dim(v):
    """Runware wants dimensions in multiples of 64 within a sane range."""
    return int(max(512, min(2048, round(v / 64) * 64)))


def size_for_ratio(cols, rows, base=1024):
    """(width, height) near `base` px matching a map's grid ratio, clamped to
    2:1 either way — so a 30×20 map gets a landscape canvas."""
    try:
        ratio = float(cols) / float(rows)
    except (TypeError, ValueError, ZeroDivisionError):
        return (base, base)
    ratio = max(0.5, min(2.0, ratio))
    if ratio >= 1:
        return (_dim(base * ratio), _dim(base))
    return (_dim(base), _dim(base / ratio))


# ── generation ──────────────────────────────────────────────────────────────

def _friendly(status, msg):
    low = (msg or '').lower()
    if status == 401 or 'invalid api key' in low or 'unauthorized' in low:
        return ('Runware rejected the API key — check it under '
                'Utilities → AI Generation.')
    if 'insufficient' in low and 'credit' in low:
        return 'Runware: out of credit — top up at my.runware.ai.'
    return f'Runware: {msg}'


def _check(resp):
    try:
        data = resp.json()
    except ValueError:
        raise RunwareError(f'Runware returned HTTP {resp.status_code} with an '
                           'unreadable body.')
    errs = data.get('errors') if isinstance(data, dict) else None
    if not errs and isinstance(data, dict) and not resp.ok:
        errs = [data]
    if errs:
        e = errs[0] if isinstance(errs, list) else errs
        msg = (e.get('message') or e.get('error') or str(e)) if isinstance(e, dict) else str(e)
        raise RunwareError(_friendly(resp.status_code, msg))
    if not resp.ok:
        raise RunwareError(f'Runware returned HTTP {resp.status_code}.')
    if not isinstance(data, dict) or not data.get('data'):
        raise RunwareError('Runware returned an empty response.')
    return data


def _unsupported_param(err):
    """The task parameter a model rejected ('Unsupported use of X parameter.
    This parameter is not supported for the selected model.'), or None.
    Models differ: FLUX takes seedImage+strength, Gemini-family (Nano
    Banana) takes seedImage but no strength, others take neither — dropping
    the offending parameter and retrying covers all of them."""
    import re
    m = re.search(r"unsupported use of '?([A-Za-z]+)'? parameter", str(err),
                  re.I)
    return m.group(1) if m else None


_MODEL_CACHE = {}


def instruction_native(model):
    """True for models that behave like Gemini (Nano Banana & friends):
    they FOLLOW instruction prompts and edit seed images natively, so the
    diffusion workarounds (prompt distillation, dark schematic seed,
    negative prompts) must NOT be applied to them. Catalog lookup, cached;
    unknown/unreachable → False (assume diffusion)."""
    if model not in _MODEL_CACHE:
        m = lookup_model(model) or {}
        arch = (m.get('architecture') or '').lower()
        _MODEL_CACHE[model] = 'gemini' in arch or 'gpt' in arch
    return _MODEL_CACHE[model]


def _post(task, key, timeout):
    try:
        resp = requests.post(
            API_URL, json=[task], timeout=timeout,
            headers={'Authorization': f'Bearer {key}',
                     'Content-Type': 'application/json'})
    except requests.RequestException as exc:
        raise RunwareError(f'Runware request failed: {exc}') from exc
    return _check(resp)


def generate_image(prompt, model=None, image=None, mime=None, size=None,
                   timeout=(10, 300), info=None, negative=None):
    """One image as (raw_bytes, 'png'). `image` bytes ride as the seedImage
    (the map-art schematic conditioning, like Gemini's input image); `size`
    is an optional (width, height) hint, rounded to Runware's constraints.

    Not every model accepts an input image — when the model rejects the
    seedImage parameter, the call is retried once WITHOUT it (nothing was
    billed for the rejection) and `info['seed_dropped']` is set so the
    caller can tell the DM the schematic was ignored."""
    key = load_api_key()
    if not key:
        raise RunwareError('No Runware API key configured — add one under '
                           'Utilities → AI Generation.')
    width, height = size or (1024, 1024)
    body = (prompt or '')[:PROMPT_MAX - len(NO_TEXT_SUFFIX)]
    task = {
        'taskType': 'imageInference',
        'taskUUID': str(uuid.uuid4()),
        'positivePrompt': body + NO_TEXT_SUFFIX,
        'negativePrompt': NEGATIVE_PROMPT + (', ' + negative if negative else ''),
        'model': model or resolve_model(),
        'width': _dim(width),
        'height': _dim(height),
        'numberResults': 1,
        'outputType': 'base64Data',
        'outputFormat': 'PNG',
    }
    if image:
        data_uri = ('data:%s;base64,' % (mime or 'image/png')
                    + base64.b64encode(image).decode('ascii'))
        if instruction_native(model or task['model']):
            # Gemini-family models take input pictures as referenceImages
            # (seedImage/strength are diffusion concepts they reject).
            task['referenceImages'] = [data_uri]
        else:
            task['seedImage'] = data_uri
            task['strength'] = SEED_STRENGTH
    # Retry, adapting to whichever parameter the model refuses (a rejection
    # is not billed): a refused seedImage is CONVERTED to referenceImages
    # (the Gemini-family channel) before the image is given up on; only
    # actually losing the input image is worth telling the DM about.
    for _attempt in range(5):
        try:
            data = _post(task, key, timeout)
            break
        except RunwareError as err:
            param = _unsupported_param(err)
            if not param or param not in task:
                raise
            value = task.pop(param)
            if param == 'seedImage':
                task.pop('strength', None)
                task['referenceImages'] = [value]
            elif param == 'referenceImages':
                if info is not None:
                    info['seed_dropped'] = True
            task['taskUUID'] = str(uuid.uuid4())
    else:
        raise RunwareError('Runware kept rejecting the request parameters.')
    entry = data['data'][0]
    b64 = entry.get('imageBase64Data')
    if not b64:
        raise RunwareError('Runware returned no image data.')
    try:
        return base64.b64decode(b64), 'png'
    except Exception as exc:
        raise RunwareError('Runware returned unreadable image data.') from exc
