"""Grid layout for the OBS party scene — pure geometry, no Flask, no sockets.

Every player is a tile in one shared scene, and every tile is the SAME size:
the turn no longer scales anyone up. Nothing reflows when the turn moves —
each tile keeps its cell for the whole session, so the audience can learn where
someone sits and never lose them.

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


def grid_layout(n, canvas_w=1920, canvas_h=1080, featured=None,
                gutter=DEFAULT_GUTTER, area=None):
    """Rects for n tiles, in slot order. Every tile is the same size.

    featured: index of the active player, or None. It is only reported back
    on the rect — it no longer changes any geometry. Scaling the active tile
    up meant the layout shifted under the audience on every turn; whose turn
    it is now reads off the title strip instead.

    area: (x, y, w, h) to lay out within — defaults to the whole canvas. The
    frame passes the leftover region so tiles never sit under the panel.

    Returns [{'x','y','w','h','featured'}].
    """
    if n <= 0:
        return []
    ax, ay, aw, ah = area if area else (0, 0, canvas_w, canvas_h)
    cols, rows = choose_grid(n, aw, ah)
    cell_w = aw / cols
    cell_h = ah / rows

    out = []
    for i in range(n):
        row = i // cols
        col = i % cols
        # Centre a short last row instead of leaving a hole on the right.
        in_this_row = min(cols, n - row * cols)
        row_offset = (cols - in_this_row) * cell_w / 2.0

        x = ax + col * cell_w + row_offset + gutter / 2.0
        y = ay + row * cell_h + gutter / 2.0
        w = cell_w - gutter
        h = cell_h - gutter

        out.append({'x': round(x, 2), 'y': round(y, 2),
                    'w': round(max(w, 1.0), 2), 'h': round(max(h, 1.0), 2),
                    'featured': featured is not None and i == featured})
    return out
