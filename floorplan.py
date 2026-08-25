"""Floorplan JSON validation for the battle-map 3D mode.

Schema v2 (produced by a vision LLM tracing the map image, by a text LLM
designing a layout, or by the DM's 2D wall editor; consumed by battlemap3d.js
on both the local pages and the relay portal):

    {
      "format": "sceneplay-floorplan",
      "schema_version": 2,
      "grid": {"cols": 20, "rows": 20},
      "default_wall_height_ft": 10,
      "sky":        {"time":"evening","weather":"cloudy"},
      "walls":      [{"x1":3,"y1":0,"x2":3,"y2":6.5, "height_ft":15, "base_ft":0,
                      "style":"stone", "texture":"mossy_stone"}],
      "doors":      [{"id":"d1","x1":3,"y1":6.5,"x2":3,"y2":7.5,"open":false,
                      "height_ft":8, "texture":"oak_planks"}],
      "elevations": [{"x1":5,"y1":5,"x2":9,"y2":9,"floor_ft":-10,"label":"pit",
                      "rot":30}],
      "lights":     [{"x":4,"y":6,"type":"torch","color":"#ff9a3c",
                      "intensity":1.0,"radius_ft":30,"height_ft":6,"flicker":true}],
      "props":      [{"type":"barrel","x":5,"y":5.4,"rot":40,"scale":1,
                      "texture":"oak_planks"}],
      "zones":      [{"id":"z1","name":"Great Hall",
                      "rects":[{"x1":2,"y1":2,"x2":10,"y2":8}],
                      "floor_texture":"flagstone","wall_texture":"castle_stone",
                      "ceiling_texture":"rough_planks","ceiling_ft":12,
                      "wall_style":"stone"}]
    }

A zone with a ceiling_texture gets a ceiling over its rects at ceiling_ft
above the local floor (default: the map's wall height). Ceilings are drawn
one-sided — seen from inside the room, never from an overhead view — so a
ceilinged map is still readable from the top-down / overview cameras.

v1 documents (no lights/props/zones, no texture refs) are a strict subset and
are accepted forever; validation stamps the current version on output.
Texture refs are library slugs — unknown names are WARNINGS, never errors:
the renderer falls back to art-sampled surfaces, so plans and the texture
library may drift apart without breaking.

Coordinates are grid cells: origin top-left, x = columns rightward,
y = rows DOWNWARD, fractional allowed (1-ft precision = 0.2 cells). Heights
are D&D feet (1 cell = 5 ft).
Pure functions, no Flask imports — the routes layer owns persistence.
"""
import re

SCHEMA_VERSION = 2
ACCEPTED_VERSIONS = (1, 2)

MAX_WALLS      = 2000
MAX_DOORS      = 200
MAX_ELEVATIONS = 200
MAX_LIGHTS     = 200
MAX_PROPS      = 300
MAX_ZONES      = 50
MAX_ZONE_RECTS = 20
# Texture-library refs a zone may carry. Every collector that decides which
# bitmaps the relay must be sent iterates THIS — add a surface here and the
# push, the missing-texture check and validation all pick it up together.
ZONE_TEXTURE_KEYS = ('floor_texture', 'wall_texture', 'ceiling_texture')
# Map-wide sky dome (renderer: battlemap3d.js SKY_PRESETS). Stored as
# {"time": ..., "weather": ...}; absent = the classic dark void. rain/snow/
# storm imply cloud cover and add camera-following precipitation (storm =
# rain + lightning) that stays out of ceilinged zones.
SKY_TIMES    = ('night', 'morning', 'afternoon', 'evening')
SKY_WEATHERS = ('clear', 'cloudy', 'rain', 'snow', 'storm')
# Ceiling height above the zone's local floor. Floor is eye height (5 ft)
# plus headroom so the first-person camera can never sit above the ceiling.
CEILING_FT_RANGE = (7.0, 60.0)
MAX_JSON_BYTES = 1024 * 1024

DEFAULT_WALL_HEIGHT_FT = 10
# Doors default to the plan's wall height (a shorter door would leave a hole
# above the frame in 3D; the renderer fills explicit shorter doors with a
# lintel block instead).
HEIGHT_FT_RANGE = (1, 100)     # wall/door height_ft
LEVEL_FT_RANGE  = (-50, 100)   # base_ft / floor_ft

# Optional wall surface finish (whole-plan default, per-zone, or per-segment),
# drawn by the 3D renderer over the colors it samples from the map art.
# 'none'/absent = smooth (default).
WALL_STYLES = {'none', 'brick', 'stone', 'wood'}

# Placeable light sources. Per-type defaults live in the renderer
# (battlemap3d.js LIGHT_DEFAULTS — keep in sync); the validator only clamps
# explicit overrides so stored plans stay minimal.
LIGHT_TYPES = {'torch', 'brazier', 'lantern', 'candle', 'glow'}
LIGHT_INTENSITY_RANGE = (0.1, 3.0)
LIGHT_RADIUS_FT_RANGE = (5, 120)
LIGHT_HEIGHT_FT_RANGE = (0, 50)

# Procedural prop set (battlemap3d.js propGeometry — keep in sync).
PROP_TYPES = {'pillar', 'crate', 'barrel', 'table', 'chair', 'chest', 'statue',
              'stairs', 'rubble', 'bed', 'shelf', 'altar',
              # outdoor / biome scenery
              'tree', 'pine', 'dead_tree', 'bush', 'stump', 'log', 'boulder',
              'campfire', 'tent', 'cactus', 'well', 'cart',
              # modern / sci-fi
              'console', 'wreck', 'barricade'}
PROP_SCALE_RANGE = (0.25, 4.0)

# Default surface bitmap per prop type (builtin texture-library slugs) —
# mirrors battlemap3d.js PROP_DEFAULT_TEX (keep in sync). The renderer
# resolves these client-side; the server's job is to ship the FILES to
# remote viewers, so the relay push includes them for every prop type the
# plan uses (routes/battlemap.py _push_map_state).
PROP_DEFAULT_TEXTURES = {
    'pillar': 'medieval_stone', 'crate': 'rough_planks', 'barrel': 'oak_planks',
    'table': 'dark_wood_floor', 'chair': 'dark_wood_floor', 'chest': 'oak_planks',
    'statue': 'marble_floor', 'stairs': 'flagstone', 'rubble': 'cave_rock',
    'bed': 'rough_planks', 'shelf': 'dark_wood_floor', 'altar': 'stone_blocks',
    'tree': 'mossy_grass', 'pine': 'mossy_grass', 'dead_tree': 'rough_planks',
    'bush': 'mossy_grass', 'stump': 'rough_planks', 'log': 'rough_planks',
    'boulder': 'cave_rock', 'campfire': 'cave_rock', 'tent': 'desert_sand',
    'cactus': 'mossy_grass', 'well': 'medieval_stone', 'cart': 'rough_planks',
    'console': 'hull_panels', 'wreck': 'rusty_metal', 'barricade': 'rough_planks',
}

# Texture library slugs (see routes/textures.py). Shape-only validation here.
TEXTURE_REF_RE = re.compile(r'^[a-z0-9_-]{1,64}$')
_HEX_COLOR_RE = re.compile(r'^#[0-9a-fA-F]{6}$')


def _num(v):
    """Coerce to float, or None if not a finite number."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    if v != v or v in (float('inf'), float('-inf')):
        return None
    return float(v)


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def _segment(raw, sx, sy, cols, rows, errors, where):
    """Validate/normalize one wall or door segment. Returns dict or None.
    sx/sy rescale LLM coordinates onto the map grid (1.0 = no-op)."""
    if not isinstance(raw, dict):
        errors.append(f'{where}: not an object')
        return None
    pts = {}
    for k in ('x1', 'y1', 'x2', 'y2'):
        v = _num(raw.get(k))
        if v is None:
            errors.append(f'{where}: missing/invalid "{k}"')
            return None
        scale = sx if k[0] == 'x' else sy
        bound = cols if k[0] == 'x' else rows
        pts[k] = round(_clamp(v * scale, 0.0, float(bound)), 2)
    if pts['x1'] == pts['x2'] and pts['y1'] == pts['y2']:
        return None    # zero-length after clamping — silently drop
    return pts


def _height(raw, key, default, errors, where):
    v = raw.get(key)
    if v is None:
        return default
    n = _num(v)
    if n is None:
        errors.append(f'{where}: invalid "{key}"')
        return default
    lo, hi = HEIGHT_FT_RANGE if key == 'height_ft' else LEVEL_FT_RANGE
    return round(_clamp(n, lo, hi), 1)


def _texture_ref(raw, key, warnings, where):
    """Shape-validate a texture library slug. Returns the slug or None.
    Bad shapes are dropped with a warning — never an error (the renderer
    falls back to art-sampled surfaces for anything it can't resolve)."""
    v = raw.get(key)
    if v is None:
        return None
    v = str(v).strip().lower()
    if not v:
        return None
    if not TEXTURE_REF_RE.match(v):
        warnings.append(f'{where}: invalid texture ref {v!r} ignored')
        return None
    return v


def _carve_doorways(walls, doors, warnings):
    """Deterministically enforce "a door covers a GAP in the wall".

    LLMs keep ending wall segments inside a doorway — or drawing the wall
    straight through it and laying the door on top — no matter how firmly
    the prompt forbids it. Rather than beg harder, normalize: any wall
    running ALONG a doorway (both door endpoints within TOL of the wall's
    line) has the doorway's span carved out, its cut ends snapped exactly to
    the door's endpoints (the jambs). Walls that merely CROSS or touch the
    door line at an angle (T-junctions, perpendicular walls) are left alone.
    Carved pieces inherit the wall's fields (height, texture, show...) and
    are re-checked against the remaining doors.
    """
    TOL = 0.3         # cells — how far off the wall's line a door may sit
    MIN_PIECE = 0.15  # cells — slivers below this are dropped
    EPS = 0.05        # cells — ignore grazing overlaps
    out = []
    trimmed = 0
    queue = list(walls)
    while queue:
        w = queue.pop(0)
        wx, wy = w['x2'] - w['x1'], w['y2'] - w['y1']
        wlen = (wx * wx + wy * wy) ** 0.5
        if wlen < 1e-9:
            continue
        ux, uy = wx / wlen, wy / wlen
        carved = False
        for d in doors:
            def _perp(px, py):
                return abs((px - w['x1']) * uy - (py - w['y1']) * ux)
            if _perp(d['x1'], d['y1']) > TOL or _perp(d['x2'], d['y2']) > TOL:
                continue      # not collinear with this wall — leave it
            s1 = (d['x1'] - w['x1']) * ux + (d['y1'] - w['y1']) * uy
            s2 = (d['x2'] - w['x1']) * ux + (d['y2'] - w['y1']) * uy
            sa, sb = (s1, s2) if s1 <= s2 else (s2, s1)
            if min(wlen, sb) - max(0.0, sa) <= EPS:
                continue      # doorway span doesn't really overlap this wall
            if s1 <= s2:
                jstart, jend = (d['x1'], d['y1']), (d['x2'], d['y2'])
            else:
                jstart, jend = (d['x2'], d['y2']), (d['x1'], d['y1'])
            carved = True
            trimmed += 1
            if sa >= MIN_PIECE:                      # piece before the door
                before = dict(w)
                before['x2'], before['y2'] = round(jstart[0], 2), round(jstart[1], 2)
                queue.append(before)
            if wlen - sb >= MIN_PIECE:               # piece after the door
                after = dict(w)
                after['x1'], after['y1'] = round(jend[0], 2), round(jend[1], 2)
                queue.append(after)
            break             # wall replaced; pieces re-run the door loop
        if not carved:
            out.append(w)
    if trimmed:
        warnings.append(
            f'{trimmed} wall segment{"s" if trimmed != 1 else ""} overlapped a '
            f'doorway — trimmed back to the door edges')
    return out


def _wall_style(raw, key, warnings, where):
    """Per-segment/zone wall style. Returns a non-'none' style or None."""
    v = raw.get(key)
    if v is None:
        return None
    v = str(v).strip().lower()
    if v and v not in WALL_STYLES:
        warnings.append(f'{where}: unknown style {v!r} ignored')
        return None
    return v if v and v != 'none' else None


def validate_floorplan(data, grid_cols, grid_rows):
    """Validate a raw floorplan dict against a map's grid.

    Returns (clean, warnings, errors). clean is None when errors is non-empty.
    A grid mismatch between the JSON and the map is rescaled with a warning —
    vision LLMs frequently miscount grid squares, and rescaling preserves the
    trace's proportions.
    """
    warnings, errors = [], []

    if not isinstance(data, dict):
        return None, warnings, ['floorplan must be a JSON object']

    ver = data.get('schema_version', 1)
    if ver not in ACCEPTED_VERSIONS:
        return None, warnings, [f'unsupported schema_version {ver!r} '
                                f'(expected one of {list(ACCEPTED_VERSIONS)})']

    grid = data.get('grid')
    sx = sy = 1.0
    if isinstance(grid, dict):
        gc, gr = _num(grid.get('cols')), _num(grid.get('rows'))
        if not gc or not gr or gc <= 0 or gr <= 0 or gc > 200 or gr > 200:
            return None, warnings, ['grid.cols/grid.rows must be numbers in 1-200']
        if int(gc) != grid_cols or int(gr) != grid_rows:
            sx = grid_cols / gc
            sy = grid_rows / gr
            warnings.append(
                f'floorplan grid {int(gc)}x{int(gr)} does not match the map grid '
                f'{grid_cols}x{grid_rows} — coordinates were rescaled to fit')
    elif grid is not None:
        return None, warnings, ['"grid" must be an object with cols/rows']

    default_h = _height(data, 'default_wall_height_ft', DEFAULT_WALL_HEIGHT_FT,
                        errors, 'default_wall_height_ft')
    # default_wall_height_ft shares height bounds, not level bounds
    default_h = round(_clamp(default_h, *HEIGHT_FT_RANGE), 1)

    raw_walls  = data.get('walls', [])
    raw_doors  = data.get('doors', [])
    raw_elevs  = data.get('elevations', [])
    raw_lights = data.get('lights', [])
    raw_props  = data.get('props', [])
    raw_zones  = data.get('zones', [])
    for name, lst, cap in (('walls', raw_walls, MAX_WALLS),
                           ('doors', raw_doors, MAX_DOORS),
                           ('elevations', raw_elevs, MAX_ELEVATIONS),
                           ('lights', raw_lights, MAX_LIGHTS),
                           ('props', raw_props, MAX_PROPS),
                           ('zones', raw_zones, MAX_ZONES)):
        if not isinstance(lst, list):
            errors.append(f'"{name}" must be a list')
        elif len(lst) > cap:
            errors.append(f'too many {name} ({len(lst)} > {cap})')
    if errors:
        return None, warnings, errors

    walls = []
    for i, raw in enumerate(raw_walls):
        seg = _segment(raw, sx, sy, grid_cols, grid_rows, errors, f'walls[{i}]')
        if seg is None:
            continue
        h = _height(raw, 'height_ft', default_h, errors, f'walls[{i}]')
        b = _height(raw, 'base_ft', 0.0, errors, f'walls[{i}]')
        if h != default_h:
            seg['height_ft'] = h
        if b:
            seg['base_ft'] = b
        if raw.get('show'):
            seg['show'] = True    # players see this wall on the 2D map too
        style = _wall_style(raw, 'style', warnings, f'walls[{i}]')
        if style:
            seg['style'] = style
        tex = _texture_ref(raw, 'texture', warnings, f'walls[{i}]')
        if tex:
            seg['texture'] = tex
        walls.append(seg)

    doors, seen_ids, auto_n = [], set(), 0
    for i, raw in enumerate(raw_doors):
        seg = _segment(raw, sx, sy, grid_cols, grid_rows, errors, f'doors[{i}]')
        if seg is None:
            continue
        did = raw.get('id') if isinstance(raw, dict) else None
        did = str(did).strip()[:32] if did else ''
        while not did or did in seen_ids:
            auto_n += 1
            did = f'd{auto_n}'
        seen_ids.add(did)
        seg['id'] = did
        seg['open'] = bool(raw.get('open', False))
        h = _height(raw, 'height_ft', default_h, errors, f'doors[{i}]')
        if h != default_h:
            seg['height_ft'] = h
        tex = _texture_ref(raw, 'texture', warnings, f'doors[{i}]')
        if tex:
            seg['texture'] = tex
        doors.append(seg)

    # Doors must sit in a GAP: trim any wall that runs along a doorway back
    # to the door's edges (LLM output regularly violates this — see helper).
    walls = _carve_doorways(walls, doors, warnings)

    elevs = []
    for i, raw in enumerate(raw_elevs):
        # Circle form (editor's round pit/platform tool): center + radius.
        if isinstance(raw, dict) and raw.get('shape') == 'circle':
            cx, cy, r = _num(raw.get('cx')), _num(raw.get('cy')), _num(raw.get('r'))
            floor = _num(raw.get('floor_ft'))
            if cx is None or cy is None or r is None or floor is None:
                errors.append(f'elevations[{i}]: circle needs cx, cy, r, floor_ft')
                continue
            r = round(_clamp(r * max(sx, sy), 0.25, float(max(grid_cols, grid_rows))), 2)
            circ = {'shape': 'circle',
                    'cx': round(_clamp(cx * sx, 0.0, float(grid_cols)), 2),
                    'cy': round(_clamp(cy * sy, 0.0, float(grid_rows)), 2),
                    'r': r,
                    'floor_ft': round(_clamp(floor, *LEVEL_FT_RANGE), 1)}
            label = raw.get('label')
            if label:
                circ['label'] = str(label).strip()[:40]
            elevs.append(circ)
            continue
        seg = _segment(raw, sx, sy, grid_cols, grid_rows, errors, f'elevations[{i}]')
        if seg is None:
            continue
        # Normalize so x1<x2, y1<y2 (rect corners in any order are fine).
        x1, x2 = sorted((seg['x1'], seg['x2']))
        y1, y2 = sorted((seg['y1'], seg['y2']))
        if x1 == x2 or y1 == y2:
            continue
        floor = _num(raw.get('floor_ft'))
        if floor is None:
            errors.append(f'elevations[{i}]: missing/invalid "floor_ft"')
            continue
        rect = {'x1': x1, 'y1': y1, 'x2': x2, 'y2': y2,
                'floor_ft': round(_clamp(floor, *LEVEL_FT_RANGE), 1)}
        # Optional rotation (degrees clockwise about the rect's CENTER) —
        # angled platforms/pits. Circles ignore it, absent/0 = axis-aligned.
        rot = _num(raw.get('rot'))
        if rot:
            rot = round(rot % 360, 1)
            if rot:
                rect['rot'] = rot
        label = raw.get('label')
        if label:
            rect['label'] = str(label).strip()[:40]
        elevs.append(rect)

    lights = []
    for i, raw in enumerate(raw_lights):
        where = f'lights[{i}]'
        if not isinstance(raw, dict):
            warnings.append(f'{where}: not an object — dropped')
            continue
        x, y = _num(raw.get('x')), _num(raw.get('y'))
        if x is None or y is None:
            warnings.append(f'{where}: missing/invalid x/y — dropped')
            continue
        ltype = str(raw.get('type') or 'torch').strip().lower()
        if ltype not in LIGHT_TYPES:
            warnings.append(f'{where}: unknown type {ltype!r} — treated as torch')
            ltype = 'torch'
        light = {'x': round(_clamp(x * sx, 0.0, float(grid_cols)), 2),
                 'y': round(_clamp(y * sy, 0.0, float(grid_rows)), 2),
                 'type': ltype}
        color = raw.get('color')
        if color is not None:
            color = str(color).strip()
            if _HEX_COLOR_RE.match(color):
                light['color'] = color.lower()
            else:
                warnings.append(f'{where}: invalid color {color!r} ignored '
                                f'(want "#rrggbb")')
        for key, rng in (('intensity', LIGHT_INTENSITY_RANGE),
                         ('radius_ft', LIGHT_RADIUS_FT_RANGE),
                         ('height_ft', LIGHT_HEIGHT_FT_RANGE)):
            v = raw.get(key)
            if v is None:
                continue
            n = _num(v)
            if n is None:
                warnings.append(f'{where}: invalid "{key}" ignored')
                continue
            light[key] = round(_clamp(n, *rng), 2)
        if raw.get('flicker') is not None:
            light['flicker'] = bool(raw.get('flicker'))
        lights.append(light)

    props = []
    for i, raw in enumerate(raw_props):
        where = f'props[{i}]'
        if not isinstance(raw, dict):
            warnings.append(f'{where}: not an object — dropped')
            continue
        ptype = str(raw.get('type') or '').strip().lower()
        if ptype not in PROP_TYPES:
            warnings.append(f'{where}: unknown prop type {ptype!r} — dropped')
            continue
        x, y = _num(raw.get('x')), _num(raw.get('y'))
        if x is None or y is None:
            warnings.append(f'{where}: missing/invalid x/y — dropped')
            continue
        prop = {'type': ptype,
                'x': round(_clamp(x * sx, 0.0, float(grid_cols)), 2),
                'y': round(_clamp(y * sy, 0.0, float(grid_rows)), 2)}
        rot = _num(raw.get('rot'))
        if rot:
            prop['rot'] = round(rot % 360, 1)
        scale = _num(raw.get('scale'))
        if scale is not None and scale > 0 and scale != 1:
            prop['scale'] = round(_clamp(scale, *PROP_SCALE_RANGE), 2)
        tex = _texture_ref(raw, 'texture', warnings, where)
        if tex:
            prop['texture'] = tex
        props.append(prop)

    zones, zone_ids, zauto = [], set(), 0
    for i, raw in enumerate(raw_zones):
        where = f'zones[{i}]'
        if not isinstance(raw, dict):
            warnings.append(f'{where}: not an object — dropped')
            continue
        raw_rects = raw.get('rects')
        if not isinstance(raw_rects, list) or not raw_rects:
            warnings.append(f'{where}: missing "rects" — dropped')
            continue
        if len(raw_rects) > MAX_ZONE_RECTS:
            warnings.append(f'{where}: too many rects '
                            f'({len(raw_rects)} > {MAX_ZONE_RECTS}) — extra dropped')
            raw_rects = raw_rects[:MAX_ZONE_RECTS]
        rects = []
        for j, rr in enumerate(raw_rects):
            seg = _segment(rr, sx, sy, grid_cols, grid_rows, errors,
                           f'{where}.rects[{j}]')
            if seg is None:
                continue
            x1, x2 = sorted((seg['x1'], seg['x2']))
            y1, y2 = sorted((seg['y1'], seg['y2']))
            if x1 == x2 or y1 == y2:
                continue
            rects.append({'x1': x1, 'y1': y1, 'x2': x2, 'y2': y2})
        if not rects:
            warnings.append(f'{where}: no usable rects — dropped')
            continue
        zid = str(raw.get('id') or '').strip()[:32]
        while not zid or zid in zone_ids:
            zauto += 1
            zid = f'z{zauto}'
        zone_ids.add(zid)
        zone = {'id': zid, 'rects': rects}
        name = raw.get('name')
        if name:
            zone['name'] = str(name).strip()[:60]
        for key in ZONE_TEXTURE_KEYS:
            tex = _texture_ref(raw, key, warnings, where)
            if tex:
                zone[key] = tex
        cft = _num(raw.get('ceiling_ft'))
        if cft is not None:
            zone['ceiling_ft'] = round(_clamp(cft, *CEILING_FT_RANGE), 1)
        style = _wall_style(raw, 'wall_style', warnings, where)
        if style:
            zone['wall_style'] = style
        zones.append(zone)

    if errors:
        return None, warnings, errors

    clean = {
        'format': 'sceneplay-floorplan',
        'schema_version': SCHEMA_VERSION,
        'grid': {'cols': grid_cols, 'rows': grid_rows},
        'default_wall_height_ft': default_h,
        'walls': walls,
        'doors': doors,
        'elevations': elevs,
    }
    # v2 layers are stored only when present, so v1-era plans (and the JSON
    # pushed to older portal viewers) stay byte-compatible.
    if lights:
        clean['lights'] = lights
    if props:
        clean['props'] = props
    if zones:
        clean['zones'] = zones

    style = str(data.get('wall_style') or '').strip().lower()
    if style and style not in WALL_STYLES:
        warnings.append(f'unknown wall_style {style!r} ignored')
    elif style and style != 'none':
        clean['wall_style'] = style

    sky = data.get('sky')
    if isinstance(sky, dict):
        stime = str(sky.get('time') or '').strip().lower()
        sweather = str(sky.get('weather') or 'clear').strip().lower()
        if stime and stime not in SKY_TIMES:
            warnings.append(f'unknown sky time {stime!r} ignored')
        elif stime:
            if sweather not in SKY_WEATHERS:
                warnings.append(f'unknown sky weather {sweather!r} — using clear')
                sweather = 'clear'
            clean['sky'] = {'time': stime, 'weather': sweather}
    elif sky not in (None, '', {}):
        warnings.append('sky: not an object — ignored')

    # Player 2D visibility switches (whole plan): show ALL walls+doors and/or
    # all props on the players' flat map — not just per-wall "show" flags.
    # Stored only when true, so plans without them stay byte-identical.
    if data.get('show_walls_2d'):
        clean['show_walls_2d'] = True
    if data.get('show_props_2d'):
        clean['show_props_2d'] = True

    import json
    if len(json.dumps(clean)) > MAX_JSON_BYTES:
        return None, warnings, [f'floorplan too large (> {MAX_JSON_BYTES // 1024} KB)']
    if not walls and not doors:
        warnings.append('floorplan has no walls or doors — 3D mode will show an open field')
    return clean, warnings, []


def floorplan_summary(clean):
    """Short status line, e.g. '42 walls · 5 doors · 2 elevation regions'."""
    parts = [f"{len(clean.get('walls', []))} walls",
             f"{len(clean.get('doors', []))} doors"]
    n = len(clean.get('elevations', []))
    if n:
        parts.append(f'{n} elevation region{"s" if n != 1 else ""}')
    for key, label in (('lights', 'light'), ('props', 'prop'), ('zones', 'zone')):
        n = len(clean.get(key, []))
        if n:
            parts.append(f'{n} {label}{"s" if n != 1 else ""}')
    return ' · '.join(parts)


# The art prompt caps door/elevation prose at this many lines: an image model
# can't act on hundreds of coordinates, and the schematic image carries the
# exact geometry anyway.
LAYOUT_TEXT_MAX_ITEMS = 20


def _fmt(v):
    """Trim float noise: 6.0 -> '6', 6.5 -> '6.5'."""
    return f'{v:g}'


def _region(mx, my, cols, rows):
    """Coarse position of a midpoint, by thirds: 'top-left area' … 'center'."""
    col = 'left' if mx < cols / 3 else ('right' if mx > cols * 2 / 3 else '')
    row = 'top' if my < rows / 3 else ('bottom' if my > rows * 2 / 3 else '')
    if not col and not row:
        return 'center of the map'
    if col and row:
        return f'{row}-{col} area'
    return f'{row or col} of the map'


def floorplan_layout_text(clean):
    """Prose description of a validated plan, for the map-art prompt.

    Deterministic, feet-converted (1 cell = 5 ft). Walls are summarized in
    aggregate — the schematic image the DM attaches carries exact geometry;
    doors and elevations get one line each (capped)."""
    grid = clean.get('grid', {})
    cols, rows = grid.get('cols', 0), grid.get('rows', 0)
    lines = [f'Grid: {cols} x {rows} squares ({cols * 5} ft x {rows * 5} ft); '
             f'1 square = 5 ft. Coordinates below are (col, row) from the '
             f'top-left corner.']

    walls  = clean.get('walls', [])
    doors  = clean.get('doors', [])
    elevs  = clean.get('elevations', [])
    lights = clean.get('lights', [])
    props  = clean.get('props', [])
    zones  = clean.get('zones', [])
    if not walls and not doors and not elevs and not lights and not props:
        lines.append('No walls, doors, or elevations — open ground.')
        return '\n'.join(lines)

    if walls:
        xs = [w[k] for w in walls for k in ('x1', 'x2')]
        ys = [w[k] for w in walls for k in ('y1', 'y2')]
        lines.append(f'{len(walls)} wall segment{"s" if len(walls) != 1 else ""}; '
                     f'built area spans columns {_fmt(min(xs))}-{_fmt(max(xs))}, '
                     f'rows {_fmt(min(ys))}-{_fmt(max(ys))}.')

    # Deliberately NO door ids here: models paint identifiers like "d3" as
    # literal labels in the art (seen in practice) despite no-text rules.
    for d in doors[:LAYOUT_TEXT_MAX_ITEMS]:
        dx, dy = abs(d['x2'] - d['x1']), abs(d['y2'] - d['y1'])
        width_ft = _fmt(round(((dx * dx + dy * dy) ** 0.5) * 5, 1))
        region = _region((d['x1'] + d['x2']) / 2, (d['y1'] + d['y2']) / 2,
                         cols, rows)
        if dy > dx:
            where = (f'at column {_fmt(d["x1"])}, rows '
                     f'{_fmt(min(d["y1"], d["y2"]))}-{_fmt(max(d["y1"], d["y2"]))}')
            orient = 'vertical'
        elif dx > dy:
            where = (f'at row {_fmt(d["y1"])}, columns '
                     f'{_fmt(min(d["x1"], d["x2"]))}-{_fmt(max(d["x1"], d["x2"]))}')
            orient = 'horizontal'
        else:
            where = (f'from ({_fmt(d["x1"])},{_fmt(d["y1"])}) to '
                     f'({_fmt(d["x2"])},{_fmt(d["y2"])})')
            orient = 'diagonal'
        lines.append(f'A {orient} doorway {width_ft} ft wide {where} ({region}).')
    if len(doors) > LAYOUT_TEXT_MAX_ITEMS:
        lines.append(f'...and {len(doors) - LAYOUT_TEXT_MAX_ITEMS} more doorways '
                     f'(see the schematic).')

    for e in elevs[:LAYOUT_TEXT_MAX_ITEMS]:
        ft = e['floor_ft']
        if ft < 0:
            kind, amount = 'pit', f'{_fmt(-ft)} ft deep'
        elif ft > 0:
            kind, amount = 'raised platform', f'{_fmt(ft)} ft high'
        else:
            kind, amount = 'ground-level area', 'at 0 ft'
        if e.get('shape') == 'circle':
            desc = (f'Circular {kind} {amount}: radius {_fmt(e["r"] * 5)} ft, '
                    f'centered at ({_fmt(e["cx"])},{_fmt(e["cy"])})')
        else:
            w_ft = _fmt((e['x2'] - e['x1']) * 5)
            h_ft = _fmt((e['y2'] - e['y1']) * 5)
            desc = (f'{kind.capitalize()} {amount}: {w_ft} ft x {h_ft} ft, '
                    f'from ({_fmt(e["x1"])},{_fmt(e["y1"])}) to '
                    f'({_fmt(e["x2"])},{_fmt(e["y2"])})')
        if e.get('label'):
            desc += f' ("{e["label"]}")'
        lines.append(desc + '.')
    if len(elevs) > LAYOUT_TEXT_MAX_ITEMS:
        lines.append(f'...and {len(elevs) - LAYOUT_TEXT_MAX_ITEMS} more '
                     f'elevation regions (see the schematic).')

    # Named rooms give the art model semantic anchors ("the Great Hall gets
    # long tables") without any coordinates it could mis-paint.
    named = [z for z in zones if z.get('name')]
    for z in named[:LAYOUT_TEXT_MAX_ITEMS]:
        r = z['rects'][0]
        region = _region((r['x1'] + r['x2']) / 2, (r['y1'] + r['y2']) / 2,
                         cols, rows)
        lines.append(f'Room "{z["name"]}" occupies the {region}.')

    # Light sources set the mood in the art: aggregate counts by type, plus
    # coarse positions for the first few so pools of light land near the
    # fixtures the 3D renderer will place.
    if lights:
        by_type = {}
        for lt in lights:
            by_type[lt['type']] = by_type.get(lt['type'], 0) + 1
        agg = ', '.join(f'{n} {t}{"s" if n != 1 else ""}'
                        for t, n in sorted(by_type.items()))
        lines.append(f'Light sources to paint as warm pools of light: {agg}.')
        for lt in lights[:LAYOUT_TEXT_MAX_ITEMS]:
            lines.append(f'A {lt["type"]} near ({_fmt(lt["x"])},{_fmt(lt["y"])}) '
                         f'({_region(lt["x"], lt["y"], cols, rows)}).')
        if len(lights) > LAYOUT_TEXT_MAX_ITEMS:
            lines.append(f'...and {len(lights) - LAYOUT_TEXT_MAX_ITEMS} more '
                         f'light sources.')

    # Props are painted subtly — the 3D renderer erects real geometry for
    # them, so the art only needs to keep those spots plausible/uncluttered.
    if props:
        by_type = {}
        for p in props:
            by_type[p['type']] = by_type.get(p['type'], 0) + 1
        agg = ', '.join(f'{n} {t}{"s" if n != 1 else ""}'
                        for t, n in sorted(by_type.items()))
        lines.append(f'Furnishings present in 3D (paint at most faint floor '
                     f'shadows for them, never solid objects): {agg}.')

    if walls:
        lines.append('Everything not listed is flat open floor at ground level.')
    return '\n'.join(lines)
