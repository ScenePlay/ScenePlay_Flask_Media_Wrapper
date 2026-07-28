"""Floorplan JSON validation for the battle-map 3D mode.

Schema v1 (produced by a vision LLM tracing the map image, or by the DM's
2D wall editor; consumed by battlemap3d.js on both the local pages and the
relay portal):

    {
      "format": "sceneplay-floorplan",
      "schema_version": 1,
      "grid": {"cols": 20, "rows": 20},
      "default_wall_height_ft": 10,
      "walls":      [{"x1":3,"y1":0,"x2":3,"y2":6.5, "height_ft":15, "base_ft":0}],
      "doors":      [{"id":"d1","x1":3,"y1":6.5,"x2":3,"y2":7.5,"open":false,"height_ft":8}],
      "elevations": [{"x1":5,"y1":5,"x2":9,"y2":9,"floor_ft":-10,"label":"pit"}]
    }

Coordinates are grid cells: origin top-left, x = columns rightward,
y = rows DOWNWARD, fractional allowed. Heights are D&D feet (1 cell = 5 ft).
Pure functions, no Flask imports — the routes layer owns persistence.
"""

SCHEMA_VERSION = 1

MAX_WALLS      = 2000
MAX_DOORS      = 200
MAX_ELEVATIONS = 200
MAX_JSON_BYTES = 512 * 1024

DEFAULT_WALL_HEIGHT_FT = 10
# Doors default to the plan's wall height (a shorter door would leave a hole
# above the frame in 3D; the renderer fills explicit shorter doors with a
# lintel block instead).
HEIGHT_FT_RANGE = (1, 100)     # wall/door height_ft
LEVEL_FT_RANGE  = (-50, 100)   # base_ft / floor_ft

# Optional per-map wall surface finish, drawn by the 3D renderer over the
# colors it samples from the map art. 'none'/absent = smooth (default).
WALL_STYLES = {'none', 'brick', 'stone', 'wood'}


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
    if ver != SCHEMA_VERSION:
        return None, warnings, [f'unsupported schema_version {ver!r} (expected {SCHEMA_VERSION})']

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

    raw_walls = data.get('walls', [])
    raw_doors = data.get('doors', [])
    raw_elevs = data.get('elevations', [])
    for name, lst, cap in (('walls', raw_walls, MAX_WALLS),
                           ('doors', raw_doors, MAX_DOORS),
                           ('elevations', raw_elevs, MAX_ELEVATIONS)):
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
        doors.append(seg)

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
        label = raw.get('label')
        if label:
            rect['label'] = str(label).strip()[:40]
        elevs.append(rect)

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

    style = str(data.get('wall_style') or '').strip().lower()
    if style and style not in WALL_STYLES:
        warnings.append(f'unknown wall_style {style!r} ignored')
    elif style and style != 'none':
        clean['wall_style'] = style

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
    return ' · '.join(parts)
