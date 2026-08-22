"""RPiLED pattern registry — the single description of every light-show
routine ScenePlay can run on a WS281x strip and the parameters it honors.

Pure Python, no Flask, no hardware: imported by the web app (editor UI,
payload builder, scene summary, migration) AND by led_Run.py (the sudo'd
strip driver) so the two can never disagree about what a pattern needs.

Why a registry and not a table: the old tblLEDTypeModel was meant to describe
each routine's parameters so the editor could hide the ones that don't apply,
but nothing ever read it that way — it degraded into a per-type defaults blob
that drifted from the code. Here the spec lives next to the routines.

Vocabulary (every pattern lists the subset it uses; see PATTERNS):
  color / color2   [r, g, b]
  variance         [r, g, b]  per-channel random spread (Sparkle)
  speed            ms between steps — lower is faster
  direction        1 forward / -1 reverse
  trail, sparks, density   pattern-specific tunables
  brightness       0–1 CREATIVE level; each box multiplies it by its own
                   hardware Max brightness (tblLEDConfig) — see led_Run.Strip
  duration         seconds; 0 = run until the next scene
brightness and duration are universal — every pattern honors them.

Wire shape (LAN Remotes, relay, local tblLED mailbox) is unchanged:
  {"patterns": [{"type": "ember_rise", "color": [...], ..., "brightness": 0.6,
                 "duration": 0, "order": 1}, ...]}
'order' is the scene row's orderBy: the player (led_Run.run) plays rows in
order, shuffles rows that SHARE an order, and repeats the whole list until
the next scene. Old receivers ignore the key.
normalize() also accepts the pre-registry keys (cdiff, wait_ms, iterations)
so a not-yet-updated box or the portal's test button still lights this one.
"""

import json
from collections import OrderedDict

SCHEMA_VERSION = 2

# ---------------------------------------------------------------------------
# Generic parameter definitions
# ---------------------------------------------------------------------------
PARAM_DEFS = {
    'color': {
        'label': 'Color', 'kind': 'rgb', 'default': [255, 255, 255],
        'hint': 'Primary color',
    },
    'color2': {
        'label': 'Second color', 'kind': 'rgb', 'default': [0, 0, 0],
        'hint': 'Secondary / highlight color',
    },
    'variance': {
        'label': 'Color variance', 'kind': 'rgb', 'default': [40, 40, 40],
        'hint': 'How far each sparkle may stray from the color, per channel (0–100)',
    },
    'speed': {
        'label': 'Speed', 'kind': 'int', 'unit': 'ms', 'min': 1, 'max': 10000,
        'default': 30, 'hint': 'Delay between steps — lower is faster',
    },
    'direction': {
        'label': 'Direction', 'kind': 'choice', 'default': 1,
        'choices': [[1, 'Forward'], [-1, 'Reverse']],
    },
    'trail': {
        'label': 'Trail length', 'kind': 'int', 'unit': 'px', 'min': 0, 'max': 30,
        'default': 2, 'hint': 'Fading pixels behind the head',
    },
    'sparks': {
        'label': 'Sparks per burst', 'kind': 'int', 'min': 1, 'max': 64,
        'default': 24,
    },
    'density': {
        'label': 'Density', 'kind': 'float', 'min': 0.01, 'max': 1.0, 'step': 0.01,
        'default': 0.25, 'hint': 'Chance per frame that a new particle spawns',
    },
    'brightness': {
        'label': 'Brightness', 'kind': 'float', 'min': 0.0, 'max': 1.0, 'step': 0.05,
        'default': 1.0,
        'hint': 'Creative level 0–1. Each box multiplies this by its own Max '
                'brightness (LED Config) so colors stay true to the end of the strip.',
    },
    'duration': {
        'label': 'Duration', 'kind': 'int', 'unit': 's', 'min': 0, 'max': 86400,
        'default': 0,
        'hint': 'Seconds to run, then the next row plays. 0 = hold until the next '
                'scene (rows after this one will not play).',
    },
}

# Every pattern honors these; the editor lists them last.
UNIVERSAL_PARAMS = ('brightness', 'duration')

# Legacy types whose `iterations` was a number of SECONDS (time-based loops);
# everywhere else it was a frame/cycle count.
_LEGACY_TIME_BASED = {'aurora_drift', 'cosmic_vortex', 'digital_dreamscape',
                      'joyful_celebration'}
_LEGACY_FOREVER = 100000        # old rows used 9999999 / 99999999 as "forever"


def _P(key, name, desc, params=(), **overrides):
    """Pattern entry. `params` is the ORDERED list of generic keys the routine
    honors (universal ones are appended automatically). `overrides` maps a
    param key to label/hint/default tweaks for this pattern only."""
    return {'type': key, 'name': name, 'desc': desc, 'params': list(params),
            'overrides': overrides}


# ---------------------------------------------------------------------------
# The patterns. Order here is the order the editor's dropdown shows them.
# ---------------------------------------------------------------------------
PATTERNS = OrderedDict((p['type'], p) for p in [
    _P('solid', 'Solid',
       'Whole strip one steady color.',
       ['color']),
    _P('color_wipe', 'Color Wipe',
       'Fills the strip one pixel at a time, then holds.',
       ['color', 'speed', 'direction'],
       speed={'default': 10}),
    _P('beam', 'Beam',
       'A single bright pixel sweeps end to end, over and over.',
       ['color', 'speed', 'direction'],
       speed={'default': 2}),
    _P('marquee', 'Marquee',
       'Alternating pixels of two colors that swap places each step.',
       ['color', 'color2', 'speed'],
       speed={'default': 8}),
    _P('marquee_effect', 'Comet',
       'A bright head chases around the strip with a fading tail over a background color.',
       ['color', 'color2', 'speed', 'direction', 'trail'],
       color={'label': 'Background', 'default': [0, 0, 0]},
       color2={'label': 'Comet', 'default': [255, 255, 255]}),
    _P('sparkle', 'Sparkle',
       'Fills with the color, then random pixels twinkle to nearby shades while the whole strip gently pulses.',
       ['color', 'variance', 'speed'],
       speed={'default': 8, 'hint': 'Longest pause between twinkles'}),
    _P('eye', 'Eye Search',
       'A glowing eye darts to random spots along the strip.',
       ['color', 'speed'],
       speed={'default': 15}),
    _P('rainbow_wave', 'Rainbow Wave',
       'A full rainbow flows along the strip.',
       ['speed', 'direction'],
       speed={'default': 5}),
    _P('rainbow_rotate', 'Rainbow Rotate',
       'The whole strip fades through the rainbow together.',
       ['speed'],
       speed={'default': 1}),
    _P('lightning_strike', 'Lightning Strike',
       'A crawling bolt builds pixel by pixel, then a full-strip flash and afterglow.',
       ['color', 'color2', 'speed', 'direction'],
       color={'label': 'Sky', 'default': [0, 0, 20], 'hint': 'Background during the lull'},
       color2={'label': 'Bolt', 'default': [220, 230, 255], 'hint': 'Bolt and flash color'},
       speed={'label': 'Quiet between strikes', 'default': 2000,
              'hint': 'Average pause between strikes'}),
    _P('thunderstorm', 'Thunderstorm',
       'Falling rain streaks with lightning flashes and a distant rumble glow.',
       ['color', 'color2', 'speed', 'direction', 'density'],
       color={'label': 'Rain', 'default': [0, 10, 30], 'hint': 'Droplet color'},
       color2={'label': 'Lightning', 'default': [200, 210, 255], 'hint': 'Flash color'},
       speed={'label': 'Quiet between strikes', 'default': 2000,
              'hint': 'Average pause between strikes'},
       density={'label': 'Rain density', 'default': 0.04}),
    _P('fireworks_simulation', 'Fireworks',
       'Rockets climb with a trail and burst into drifting sparks.',
       ['color', 'color2', 'speed', 'direction', 'sparks'],
       color={'label': 'Burst', 'default': [255, 255, 255]},
       color2={'label': 'Rocket trail', 'default': [255, 50, 0]},
       speed={'default': 20}),
    _P('fireworks_finale', 'Fireworks Finale',
       'Rapid volleys of randomly colored fireworks.',
       ['speed'],
       speed={'default': 50}),
    _P('shimmer_sine_wave', 'Shimmer Wave',
       'A rolling wave of color with bright glints, like sunlight on water.',
       ['color', 'color2', 'speed', 'direction'],
       color={'label': 'Wave', 'default': [0, 60, 180]},
       color2={'label': 'Glint', 'default': [200, 220, 255]}),
    _P('shimmer_effect', 'Embers Breathing',
       'Every pixel breathes between two colors at its own pace.',
       ['color', 'color2', 'speed', 'direction'],
       color={'label': 'Dim', 'default': [180, 80, 0]},
       color2={'label': 'Bright', 'default': [255, 220, 120]},
       speed={'default': 40}),
    _P('ember_rise', 'Ember Rise',
       'Glowing embers spawn at one end and drift along, cooling as they go.',
       ['color', 'color2', 'speed', 'direction', 'density'],
       color={'label': 'Cool glow', 'default': [180, 40, 0]},
       color2={'label': 'Hot core', 'default': [255, 200, 60]},
       density={'label': 'Spawn rate', 'default': 0.25}),
    _P('serenity_flow', 'Serenity Flow',
       'Light blooms from darkness between two colors, holds, and fades away again.',
       ['color', 'color2', 'speed', 'direction'],
       color={'label': 'Origin', 'default': [0, 40, 120]},
       color2={'label': 'Far end', 'default': [120, 0, 160]}),
    _P('tranquil_drift', 'Tranquil Drift',
       'A slow wave blends two colors along the strip with a gentle breathing pulse.',
       ['color', 'color2', 'speed', 'direction'],
       color={'default': [0, 100, 200]},
       color2={'default': [0, 180, 120]},
       speed={'default': 50}),
    _P('color_chase', 'Color Chase',
       'Two colored particles chase each other, collide, and swap roles.',
       ['color', 'color2', 'speed', 'direction'],
       color={'label': 'Prey', 'default': [0, 100, 255]},
       color2={'label': 'Chaser', 'default': [255, 50, 0]},
       speed={'default': 20}),
    _P('aurora_drift', 'Aurora Drift',
       'Soft waves of shifting color drift along the strip.',
       ['speed'],
       speed={'default': 30}),
    _P('cosmic_vortex', 'Cosmic Vortex',
       'A swirling rainbow vortex that pulses in brightness.',
       ['speed'],
       speed={'default': 10}),
    _P('digital_dreamscape', 'Digital Dreamscape',
       'Layered color waves with tiny random glitches.',
       ['speed'],
       speed={'default': 8}),
    _P('joyful_celebration', 'Celebration',
       'Rainbow pulses, a chase, and confetti flashes.',
       ['speed'],
       speed={'default': 50, 'hint': 'Chase step delay'}),
])

TYPES = tuple(PATTERNS.keys())


# ---------------------------------------------------------------------------
# Introspection
# ---------------------------------------------------------------------------
def is_type(ptype):
    return ptype in PATTERNS


def display_name(ptype):
    p = PATTERNS.get(ptype)
    return p['name'] if p else str(ptype or '')


def param_keys(ptype):
    """Ordered param keys a pattern honors, universal ones last."""
    p = PATTERNS[ptype]
    return list(p['params']) + [k for k in UNIVERSAL_PARAMS if k not in p['params']]


def param_spec(ptype):
    """Full field specs (label/kind/range/default/hint) for the editor, with
    this pattern's overrides applied."""
    p = PATTERNS[ptype]
    out = []
    for key in param_keys(ptype):
        spec = dict(PARAM_DEFS[key])
        spec.update(p['overrides'].get(key, {}))
        spec['key'] = key
        out.append(spec)
    return out


def defaults(ptype):
    return {s['key']: s['default'] for s in param_spec(ptype)}


def registry_json():
    """Everything the editor page needs, JSON-serializable."""
    return {
        'schema': SCHEMA_VERSION,
        'patterns': [{'type': t, 'name': p['name'], 'desc': p['desc'],
                      'params': param_spec(t)} for t, p in PATTERNS.items()],
    }


# ---------------------------------------------------------------------------
# Coercion
# ---------------------------------------------------------------------------
def _clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


def _rgb(v, dflt):
    if isinstance(v, str):
        try:
            v = json.loads(v)
        except (TypeError, ValueError):
            return list(dflt)
    if not isinstance(v, (list, tuple)) or len(v) < 3:
        return list(dflt)
    out = []
    for c in v[:3]:
        try:
            out.append(int(_clamp(float(c), 0, 255)))
        except (TypeError, ValueError):
            return list(dflt)
    return out


def _num(v, spec, dflt):
    if v is None or v == '':
        return dflt
    try:
        f = float(v)
    except (TypeError, ValueError):
        return dflt
    f = _clamp(f, spec.get('min', f), spec.get('max', f))
    return int(round(f)) if spec['kind'] == 'int' else round(f, 3)


def coerce(ptype, params):
    """Validated, complete params dict for `ptype`: every honored key present,
    in range, unknown keys dropped. `params` may be a dict, JSON string or None."""
    if isinstance(params, str):
        try:
            params = json.loads(params)
        except (TypeError, ValueError):
            params = {}
    params = params or {}
    out = {}
    for spec in param_spec(ptype):
        key, kind, dflt = spec['key'], spec['kind'], spec['default']
        v = params.get(key)
        if kind == 'rgb':
            out[key] = _rgb(v, dflt)
        elif kind == 'choice':
            allowed = [c[0] for c in spec['choices']]
            try:
                v = int(float(v))
            except (TypeError, ValueError):
                v = dflt
            out[key] = v if v in allowed else dflt
        else:
            out[key] = _num(v, spec, dflt)
    return out


def legacy_duration(ptype, iterations, wait_ms):
    """Old `iterations` → new `duration` (seconds). 0 = forever."""
    try:
        it = int(float(iterations))
    except (TypeError, ValueError):
        return 0
    if it <= 0 or it >= _LEGACY_FOREVER:
        return 0
    if ptype in _LEGACY_TIME_BASED:
        return it
    try:
        ms = max(1, int(float(wait_ms)))
    except (TypeError, ValueError):
        ms = 30
    return max(1, int(round(it * ms / 1000.0)))


def legacy_to_params(ptype, color=None, cdiff=None, wait_ms=None,
                     iterations=None, direction=None, brightness=None):
    """Map the pre-registry scene-row columns onto the generic vocabulary.
    Used by the 0010 migration and by restore_merge for old backups.
    `brightness` is only honored when it's a real creative value: the old
    rows copied the HARDWARE config value (e.g. 0.08) in at creation, which
    would double-dim everything once the cap applies — so anything at or
    below the old default config level becomes 1.0."""
    if ptype not in PATTERNS:
        return None
    raw = {}
    if color is not None:
        raw['color'] = color
    if cdiff is not None:
        raw['variance' if ptype == 'sparkle' else 'color2'] = cdiff
    if wait_ms not in (None, ''):
        raw['speed'] = wait_ms
    if direction not in (None, ''):
        raw['direction'] = direction
    raw['duration'] = legacy_duration(ptype, iterations, wait_ms)
    try:
        b = float(brightness)
        raw['brightness'] = 1.0 if b <= 0.1 else b
    except (TypeError, ValueError):
        pass
    return coerce(ptype, raw)


def normalize(pattern):
    """One wire pattern dict (any vintage) → complete registry-shaped dict
    with 'type' plus every honored param, or None if the type is unknown.
    Legacy keys: cdiff → color2 (variance for sparkle), wait_ms → speed,
    iterations → duration; outPinID is ignored (the pin is box config)."""
    if not isinstance(pattern, dict):
        return None
    ptype = str(pattern.get('type') or '')
    if ptype not in PATTERNS:
        return None
    raw = dict(pattern)
    if 'color2' not in raw and 'variance' not in raw and 'cdiff' in raw:
        raw['variance' if ptype == 'sparkle' else 'color2'] = raw['cdiff']
    if 'speed' not in raw and 'wait_ms' in raw:
        raw['speed'] = raw['wait_ms']
    if 'duration' not in raw and 'iterations' in raw:
        raw['duration'] = legacy_duration(ptype, raw['iterations'],
                                          raw.get('wait_ms', raw.get('speed')))
    out = {'type': ptype}
    out.update(coerce(ptype, raw))
    out['order'] = _order(raw.get('order'))
    return out


def _order(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return 0


# ---------------------------------------------------------------------------
# Payload builder (replaces remotes.prepJsonRemote)
# ---------------------------------------------------------------------------
def build_payload(rows):
    """rows: iterable of (patternType, params[, orderBy]) in scene order,
    params a dict or JSON string. Returns the wire JSON string
    {"patterns": [...]}. Rows with an unknown type are skipped; an empty
    list means lights off."""
    patterns = []
    for row in rows:
        ptype, params = row[0], row[1]
        if ptype not in PATTERNS:
            continue
        p = {'type': ptype}
        p.update(coerce(ptype, params))
        p['order'] = _order(row[2]) if len(row) > 2 else 0
        patterns.append(p)
    if not patterns:
        patterns = [{'type': 'solid', 'color': [0, 0, 0]}]
    return json.dumps({'patterns': patterns})


OFF_PAYLOAD = json.dumps({'patterns': [{'type': 'solid', 'color': [0, 0, 0]}]})
