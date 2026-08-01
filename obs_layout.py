"""Grid layout for the OBS party scene — pure geometry, no Flask, no sockets.

Every player is a tile in one shared scene. With nobody featured, every tile is
the same size and the grid is even.

Featuring a player SPOTLIGHTS them: their tile spans a 2x2 block — double the
width and height of an ordinary tile — and everyone else shrinks and repacks
around it, keeping their running order. Nothing is ever drawn over anything
else, so no one is hidden while someone has the table's attention. 0 or G drops
back to the even grid.

An earlier version scaled the featured tile in place, on top of its neighbours,
and was removed because it covered people. The spotlight reflows instead: the
whole grid resizes, which is a deliberate, readable move rather than a tile
quietly swelling over the player behind it.

The canvas is a frame: a title strip along the top, an information panel down
one side, and the tiles filling what is left.

Coordinates are canvas pixels; the caller feeds them straight into
SetSceneItemTransform as bounds.
"""
import math

DEFAULT_GUTTER = 10           # px between tiles
DEFAULT_TITLE_H = 96          # px of title strip across the top
DEFAULT_PANEL_FRACTION = 0.195  # share of the canvas the info panel takes
TARGET_ASPECT = 16 / 9        # webcam tiles look best near this
SPOTLIGHT_SPAN = 2            # featured tile spans 2x2 cells = 2x linear


def choose_grid(n, canvas_w=1920, canvas_h=1080):
    """(cols, rows) for n tiles: the arrangement whose cells sit closest to
    16:9 while wasting the fewest empty cells.

    A plain ceil(sqrt(n)) gives 3x3 for 8 players — one dead cell and tall,
    narrow tiles. Scoring both terms picks 4x2 instead."""
    if n <= 0:
        return (0, 0)
    best, best_score = (n, 1), None
    for rows in range(1, n + 1):
        cols = math.ceil(n / rows)
        cell_w = canvas_w / cols
        cell_h = canvas_h / rows
        aspect_err = abs(math.log((cell_w / cell_h) / TARGET_ASPECT))
        waste = (cols * rows - n) / n
        score = aspect_err + waste * 0.6
        if best_score is None or score < best_score - 1e-9:
            best, best_score = (cols, rows), score
    return best


def frame_areas(canvas_w=1920, canvas_h=1080, panel_side='right',
                panel_fraction=DEFAULT_PANEL_FRACTION,
                title_h=DEFAULT_TITLE_H, panel_on=True):
    """Carve the canvas into {'title', 'panel', 'tiles'} rects.

    The title runs the full width along the top so it reads as a banner rather
    than a caption on one column. The panel hangs below it down one side (or
    across the bottom), and the tiles take everything left over.

    'title' and 'panel' are None when switched off, which is also how the
    caller knows to drop those sources from the scene."""
    title_h = max(0.0, min(float(title_h), canvas_h * 0.4))
    title = (0.0, 0.0, float(canvas_w), title_h) if title_h > 0 else None

    top = title_h
    body_h = canvas_h - top
    if not panel_on:
        return {'title': title, 'panel': None,
                'tiles': (0.0, top, float(canvas_w), body_h)}

    frac = min(max(float(panel_fraction), 0.12), 0.6)
    if panel_side in ('left', 'right'):
        pw = canvas_w * frac
        rest = canvas_w - pw
        if panel_side == 'left':
            panel = (0.0, top, pw, body_h)
            tiles = (pw, top, rest, body_h)
        else:
            panel = (rest, top, pw, body_h)
            tiles = (0.0, top, rest, body_h)
    else:
        ph = body_h * frac
        rest = body_h - ph
        if panel_side == 'top':
            panel = (0.0, top, float(canvas_w), ph)
            tiles = (0.0, top + ph, float(canvas_w), rest)
        else:
            panel = (0.0, top + rest, float(canvas_w), ph)
            tiles = (0.0, top, float(canvas_w), rest)
    return {'title': title, 'panel': panel, 'tiles': tiles}


def choose_spotlight_grid(n, canvas_w=1920, canvas_h=1080):
    """(cols, rows) for n tiles when one of them spans a SPOTLIGHT_SPAN square.

    The grid has to hold (n - 1) ordinary cells plus the span**2 the spotlit
    tile eats, so it is finer than the even grid for the same party — which is
    exactly why everyone else shrinks. Scored like choose_grid: cells near
    16:9, few wasted. Because the spotlit tile is just a doubled cell, keeping
    cells webcam-shaped keeps it webcam-shaped too."""
    span = SPOTLIGHT_SPAN
    if n <= 1:
        return (1, 1)
    need = (n - 1) + span * span
    best, best_score = None, None
    for rows in range(span, need + 1):
        cols = max(span, math.ceil(need / rows))
        if cols * rows < need:
            continue
        cell_w = canvas_w / cols
        cell_h = canvas_h / rows
        aspect_err = abs(math.log((cell_w / cell_h) / TARGET_ASPECT))
        waste = (cols * rows - need) / need
        score = aspect_err + waste * 0.6
        if best_score is None or score < best_score - 1e-9:
            best, best_score = (cols, rows), score
    return best or (span, span)


def _cell(ax, ay, cell_w, cell_h, row, col, gutter,
          span_c=1, span_r=1, x_offset=0.0):
    """One tile rect, sized to the cells it spans minus the gutter."""
    return {'x': round(ax + col * cell_w + x_offset + gutter / 2.0, 2),
            'y': round(ay + row * cell_h + gutter / 2.0, 2),
            'w': round(max(span_c * cell_w - gutter, 1.0), 2),
            'h': round(max(span_r * cell_h - gutter, 1.0), 2)}


def _even_layout(n, ax, ay, aw, ah, gutter, featured):
    cols, rows = choose_grid(n, aw, ah)
    cell_w = aw / cols
    cell_h = ah / rows
    out = []
    for i in range(n):
        row, col = divmod(i, cols)
        # Centre a short last row instead of leaving a hole on the right.
        in_this_row = min(cols, n - row * cols)
        offset = (cols - in_this_row) * cell_w / 2.0
        rect = _cell(ax, ay, cell_w, cell_h, row, col, gutter, x_offset=offset)
        rect['featured'] = featured is not None and i == featured
        out.append(rect)
    return out


def _spotlight_layout(n, ax, ay, aw, ah, gutter, featured):
    """The spotlit tile takes the top-left 2x2 block; everyone else flows into
    the cells it leaves, in reading order, keeping their running order."""
    span = SPOTLIGHT_SPAN
    cols, rows = choose_spotlight_grid(n, aw, ah)
    cell_w = aw / cols
    cell_h = ah / rows

    block = {(r, c) for r in range(span) for c in range(span)}
    free = [(r, c) for r in range(rows) for c in range(cols) if (r, c) not in block]
    others = [i for i in range(n) if i != featured]
    placement = list(zip(others, free))

    # Rows BELOW the block can come up short — centre those so the grid doesn't
    # look lopsided. The cells beside the block keep their column: they read as
    # the strip next to the spotlight and must not drift into it.
    per_row = {}
    for _, (r, _c) in placement:
        per_row[r] = per_row.get(r, 0) + 1

    out = [None] * n
    hero = _cell(ax, ay, cell_w, cell_h, 0, 0, gutter, span, span)
    hero['featured'] = True
    out[featured] = hero

    for idx, (r, c) in placement:
        offset = 0.0
        if r >= span and per_row[r] < cols:
            offset = (cols - per_row[r]) * cell_w / 2.0
        rect = _cell(ax, ay, cell_w, cell_h, r, c, gutter, x_offset=offset)
        rect['featured'] = False
        out[idx] = rect
    return out


def spotlight_tile_size(n, canvas_w=1920, canvas_h=1080,
                        gutter=DEFAULT_GUTTER, area=None):
    """(w, h) of the spotlit tile — the biggest any tile ever gets.

    Every browser source renders at THIS size no matter who currently holds the
    spotlight. Resizing a browser source makes OBS re-render the page, which
    blanks a camera feed for a moment; keeping the render size fixed means
    moving the spotlight only changes a transform, so nothing blinks. It also
    means an enlarged tile is never upscaled."""
    if n <= 0:
        return (0.0, 0.0)
    rects = grid_layout(n, canvas_w, canvas_h, featured=0, gutter=gutter, area=area)
    return (rects[0]['w'], rects[0]['h'])


def grid_layout(n, canvas_w=1920, canvas_h=1080, featured=None,
                gutter=DEFAULT_GUTTER, area=None):
    """Rects for n tiles, in slot order.

    featured: index of the spotlit player, or None for the even grid. The
    spotlit tile spans SPOTLIGHT_SPAN**2 cells — double the width and height of
    its neighbours — and the rest shrink and repack around it. Tiles never
    overlap in either mode.

    area: (x, y, w, h) to lay out within — defaults to the whole canvas. The
    frame passes the leftover region so tiles never sit under the panel.

    Returns [{'x','y','w','h','featured'}].
    """
    if n <= 0:
        return []
    ax, ay, aw, ah = area if area else (0, 0, canvas_w, canvas_h)
    # A lone player already fills the area — there is nothing to shrink.
    if featured is None or not 0 <= featured < n or n == 1:
        return _even_layout(n, ax, ay, aw, ah, gutter, featured)
    return _spotlight_layout(n, ax, ay, aw, ah, gutter, featured)
