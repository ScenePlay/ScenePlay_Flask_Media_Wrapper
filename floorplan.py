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

    walls = clean.get('walls', [])
    doors = clean.get('doors', [])
    elevs = clean.get('elevations', [])
    if not walls and not doors and not elevs:
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

    if walls:
        lines.append('Everything not listed is flat open floor at ground level.')
    return '\n'.join(lines)
