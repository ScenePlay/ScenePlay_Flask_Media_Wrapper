"""Google Gemini API client for the one-click AI generation flows.

Design rules (see routes/ai.py for the endpoints that use this):
  - The API key lives ONLY in instance/gemini_api_key (chmod 0600) or the
    GEMINI_API_KEY env var. instance/ is gitignored and outside DB backups,
    so the key never reaches the repo, a backup zip, or the relay. It is
    never rendered into a template or returned by any endpoint.
  - No new dependencies: plain `requests` against the v1beta REST API, auth
    via the x-goog-api-key HEADER (never a ?key= query param — keys in URLs
    end up in logs).
  - Text/JSON/vision and image generation use models/{model}:generateContent
    (the long-stable surface; Google's docs now push the newer "interactions"
    API but keep generateContent supported). Veo video uses
    :predictLongRunning + operation polling per current docs.
  - Every network call has explicit timeouts. Errors normalize into
    GeminiError with a message fit to show the DM (quota, safety blocks,
    bad model ids...).

No Flask imports — testable standalone, like relay_broadcaster.
"""
import base64
import os
import threading
import time
import uuid

API_BASE = 'https://generativelanguage.googleapis.com/v1beta'

_KEY_PATH = os.path.join(os.path.dirname(os.path.realpath(__file__)),
                         'instance', 'gemini_api_key')

# Model allowlists per modality. Google retired the 2.x generation from the
# API (2026), so only 3.x ids are offered; an id Google rejects fails loudly
# with Google's own error message, never silently. resolve_model ignores a
# stored setting that falls off this list, so boxes that had a 2.5 model
# saved drop to the new default on their own.
TEXT_MODELS = ('gemini-3.7-flash',)
IMAGE_MODELS = ('gemini-3.1-flash-image', 'gemini-3-pro-image')
VIDEO_MODELS = ('veo-3.1-fast-generate-preview', 'veo-3.1-generate-preview',
                'veo-3.0-fast-generate-001', 'veo-3.0-generate-001')

DEFAULTS = {
    'text': TEXT_MODELS[0],
    'image': IMAGE_MODELS[0],
    'video': VIDEO_MODELS[0],
}
_ALLOWED = {'text': TEXT_MODELS, 'image': IMAGE_MODELS, 'video': VIDEO_MODELS}
_SETTING_NAMES = {'text': 'gemini_model_text', 'image': 'gemini_model_image',
                  'video': 'gemini_model_video'}


class GeminiError(Exception):
    """Raised for any Gemini failure; str(e) is safe to show the DM."""


# ── API key management ───────────────────────────────────────────────────────

def load_api_key():
    """The active key: GEMINI_API_KEY env var wins, else the instance file.
    Returns None when neither is set."""
    env = (os.environ.get('GEMINI_API_KEY') or '').strip()
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
        pass   # e.g. Windows — ignored, matches the secret_key behavior


def clear_api_key():
    try:
        os.remove(_KEY_PATH)
    except OSError:
        pass


def configured():
    return load_api_key() is not None


def key_source():
    """'env' | 'file' | None — for the settings UI badge (never the key)."""
    if (os.environ.get('GEMINI_API_KEY') or '').strip():
        return 'env'
    return 'file' if configured() else None


# ── model selection ──────────────────────────────────────────────────────────

def resolve_model(modality, override=None):
    """Per-call override > the appsetting default > the built-in default.
    Anything outside the allowlist is ignored (falls through), so a stale
    stored setting can never produce a surprise model."""
    allowed = _ALLOWED[modality]
    if override and override in allowed:
        return override
    try:
        from sql import appsettingGet
        stored = appsettingGet(_SETTING_NAMES[modality], '') or ''
        if stored in allowed:
            return stored
    except Exception:
        pass
    return DEFAULTS[modality]


# ── request plumbing ─────────────────────────────────────────────────────────

def _headers():
    key = load_api_key()
    if not key:
        raise GeminiError('No Gemini API key configured — add one under '
                          'Utilities → Gemini AI.')
    return {'x-goog-api-key': key, 'Content-Type': 'application/json'}


def _friendly_http_error(resp):
    """Google's error JSON -> a message worth showing the DM."""
    msg = ''
    try:
        msg = (resp.json().get('error') or {}).get('message') or ''
    except Exception:
        pass
    if resp.status_code == 429:
        return 'Gemini quota/rate limit hit — wait a minute and retry. ' + msg
    if resp.status_code in (401, 403):
        return 'Gemini rejected the API key — check it under Utilities. ' + msg
    if resp.status_code == 404:
        return ('Model not available on this API — pick another model in '
                'Utilities. ' + msg)
    return msg or f'Gemini API error (HTTP {resp.status_code})'


def _check(resp):
    if resp.status_code >= 400:
        raise GeminiError(_friendly_http_error(resp))
    try:
        return resp.json()
    except ValueError:
        raise GeminiError('Gemini returned an unreadable response.')


def _check_candidate(data):
    """Common generateContent response validation -> the parts list."""
    block = ((data.get('promptFeedback') or {}).get('blockReason'))
    if block:
        raise GeminiError(f'Blocked by safety filter: {block}. '
                          'Rephrase the prompt and try again.')
    cands = data.get('candidates') or []
    if not cands:
        raise GeminiError('Gemini returned no result.')
    if cands[0].get('finishReason') == 'SAFETY':
        raise GeminiError('Blocked by safety filter. Rephrase the prompt '
                          'and try again.')
    content = cands[0].get('content') or {}
    return content.get('parts') or []


def _image_part(image_bytes, mime):
    return {'inline_data': {'mime_type': mime or 'image/png',
                            'data': base64.b64encode(image_bytes).decode('ascii')}}


def _part_inline(part):
    """inline data from a response part — REST answers camelCase, but accept
    snake_case defensively."""
    return part.get('inlineData') or part.get('inline_data')


# ── text / JSON / vision ─────────────────────────────────────────────────────

def generate_json(prompt, model, image=None, mime=None, timeout=(10, 180)):
    """Prompt (optionally with an attached image, for the trace flow) ->
    raw JSON text. responseMimeType pins the output to JSON so no fence
    stripping should be needed (the caller's paste pipeline strips anyway)."""
    import requests
    parts = [{'text': prompt}]
    if image:
        parts.append(_image_part(image, mime))
    body = {
        'contents': [{'parts': parts}],
        'generationConfig': {'responseMimeType': 'application/json'},
    }
    resp = requests.post(f'{API_BASE}/models/{model}:generateContent',
                         headers=_headers(), json=body, timeout=timeout)
    out = []
    for part in _check_candidate(_check(resp)):
        if part.get('text'):
            out.append(part['text'])
    text = ''.join(out).strip()
    if not text:
        raise GeminiError('Gemini returned an empty reply.')
    return text


# ── image generation ─────────────────────────────────────────────────────────

def generate_image(prompt, model, image=None, mime=None, timeout=(10, 300)):
    """Prompt (optionally conditioned on an input image — the schematic
    blueprint for map art) -> (raw_bytes, ext)."""
    import requests
    parts = [{'text': prompt}]
    if image:
        parts.append(_image_part(image, mime))
    body = {'contents': [{'parts': parts}]}
    resp = requests.post(f'{API_BASE}/models/{model}:generateContent',
                         headers=_headers(), json=body, timeout=timeout)
    for part in _check_candidate(_check(resp)):
        inline = _part_inline(part)
        if inline and inline.get('data'):
            raw = base64.b64decode(inline['data'])
            mime_type = inline.get('mimeType') or inline.get('mime_type') or ''
            ext = 'jpg' if 'jpeg' in mime_type else \
                  (mime_type.split('/')[-1] if '/' in mime_type else 'png')
            if ext not in ('png', 'jpg', 'webp', 'gif'):
                ext = 'png'
            return raw, ext
    raise GeminiError('Gemini answered without an image — try rephrasing '
                      'the prompt or another image model.')


# ── Veo video (long-running) ─────────────────────────────────────────────────

def veo_start(prompt, model, image=None, mime=None, timeout=(10, 60)):
    """Kick off a Veo generation. Returns the operation name to poll.
    The image (when given) is the starting frame — for map art that's the
    current still background the animation should bring to life."""
    import requests
    instance = {'prompt': prompt}
    if image:
        instance['image'] = {
            'inlineData': {'mimeType': mime or 'image/png',
                           'data': base64.b64encode(image).decode('ascii')},
        }
    body = {'instances': [instance],
            'parameters': {'aspectRatio': '16:9', 'resolution': '720p'}}
    resp = requests.post(f'{API_BASE}/models/{model}:predictLongRunning',
                         headers=_headers(), json=body, timeout=timeout)
    if resp.status_code == 400 and image:
        # Older Veo REST wanted {'bytesBase64Encoded', 'mimeType'} for the
        # image — retry once with that shape before giving up.
        instance['image'] = {
            'bytesBase64Encoded': base64.b64encode(image).decode('ascii'),
            'mimeType': mime or 'image/png',
        }
        resp = requests.post(f'{API_BASE}/models/{model}:predictLongRunning',
                             headers=_headers(), json=body, timeout=timeout)
    name = _check(resp).get('name')
    if not name:
        raise GeminiError('Veo did not return an operation to poll.')
    return name


def _veo_extract_video(response):
    """The finished operation's video, across the response shapes Google has
    shipped: generateVideoResponse.generatedSamples[*].video.{uri|bytes...}
    and generatedVideos[*].video. Returns (uri_or_none, bytes_or_none)."""
    holders = []
    gvr = response.get('generateVideoResponse') or {}
    holders.extend(gvr.get('generatedSamples') or [])
    holders.extend(response.get('generatedVideos') or [])
    holders.extend(gvr.get('generatedVideos') or [])
    for h in holders:
        video = h.get('video') or h
        uri = video.get('uri')
        b64 = video.get('bytesBase64Encoded') or video.get('videoBytes')
        if b64:
            return None, base64.b64decode(b64)
        if uri:
            return uri, None
    return None, None


def veo_poll(op_name, timeout=(10, 60)):
    """One poll. Returns {'done': False} or {'done': True, 'uri'/'bytes'}.
    Raises GeminiError when the operation itself failed."""
    import requests
    resp = requests.get(f'{API_BASE}/{op_name}', headers=_headers(),
                        timeout=timeout)
    data = _check(resp)
    if not data.get('done'):
        return {'done': False}
    err = data.get('error')
    if err:
        raise GeminiError('Veo generation failed: '
                          + (err.get('message') or str(err)))
    uri, raw = _veo_extract_video(data.get('response') or {})
    if raw:
        return {'done': True, 'bytes': raw}
    if uri:
        return {'done': True, 'uri': uri}
    raise GeminiError('Veo finished but returned no video.')


def veo_download(uri, timeout=(10, 300)):
    import requests
    resp = requests.get(uri, headers={'x-goog-api-key': load_api_key() or ''},
                        timeout=timeout, allow_redirects=True)
    if resp.status_code >= 400:
        raise GeminiError(f'Could not download the generated video '
                          f'(HTTP {resp.status_code}).')
    return resp.content


# ── background video jobs ────────────────────────────────────────────────────
# Veo takes 1-6 minutes: a Flask request can't wait that out, so a daemon
# thread runs the start→poll→download→save pipeline while the browser polls
# job_status(). In-memory is fine (single-process app, mirrors the relay push
# queue); a server restart loses in-flight jobs, surfaced as "unknown job".

VEO_POLL_S = 10
VEO_MAX_WAIT_S = 10 * 60
_JOB_TTL_S = 60 * 60

_jobs = {}
_jobs_lock = threading.Lock()


def _prune_jobs():
    cutoff = time.time() - _JOB_TTL_S
    with _jobs_lock:
        for jid in [j for j, rec in _jobs.items() if rec['created'] < cutoff]:
            del _jobs[jid]


def start_video_job(prompt, model, image=None, mime=None, on_success=None):
    """Returns a job id immediately. on_success(video_bytes, ext) runs on the
    worker thread once the clip is downloaded (the route wraps it in an app
    context); its return value becomes the job's `result`."""
    _prune_jobs()
    job_id = uuid.uuid4().hex
    with _jobs_lock:
        _jobs[job_id] = {'status': 'running', 'created': time.time(),
                         'error': None, 'result': None}

    def _set(**kw):
        with _jobs_lock:
            if job_id in _jobs:
                _jobs[job_id].update(kw)

    def _run():
        try:
            op = veo_start(prompt, model, image=image, mime=mime)
            deadline = time.time() + VEO_MAX_WAIT_S
            while True:
                if time.time() > deadline:
                    raise GeminiError('Veo generation timed out after '
                                      f'{VEO_MAX_WAIT_S // 60} minutes.')
                state = veo_poll(op)
                if state['done']:
                    break
                time.sleep(VEO_POLL_S)
            raw = state.get('bytes') or veo_download(state['uri'])
            result = on_success(raw, 'mp4') if on_success else None
            _set(status='done', result=result)
        except GeminiError as e:
            _set(status='error', error=str(e))
        except Exception as e:   # network blips, save failures...
            _set(status='error', error=f'Video generation failed: {e}')

    t = threading.Thread(target=_run, daemon=True, name=f'veo-{job_id[:8]}')
    t.start()
    return job_id


def job_status(job_id):
    """{'status': 'running'|'done'|'error', 'error', 'result'} or None."""
    with _jobs_lock:
        rec = _jobs.get(job_id)
        return dict(rec) if rec else None
