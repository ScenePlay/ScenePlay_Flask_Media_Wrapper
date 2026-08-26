"""Reuse an existing upload (or a library video) as another record's picture
or video — by REFERENCE, never by copying the file.

Every image/video column in the app stores a bare filename that consumers
turn into `static/uploads/<folder>/<name>` (templates via url_for, server
code via os.path.join). A shared reference is a RELATIVE PATH stored in
that same column:

    ../<folder>/<file>                 a picture in another upload folder
    ../../../assets/media/video/<id>.<ext>   a video from the download library

Browsers normalise the `..` in the URL and os.path.join resolves it on
disk, so the dozens of existing consumers work untouched; the only new
rules are (1) a reference is never deleted by the record that holds it and
(2) a file some other record references by name is not deleted when its
owner replaces it. Library videos live outside static/, so their reference
points at the inline-streaming route instead; resolve_path() maps it back
to the real file for server-side readers (the relay push).
"""
import os
import re
import sqlite3

from assets_inventory import PICTURE_FOLDERS, MEDIA_KINDS

FOLDERS = tuple(f for f, _ in PICTURE_FOLDERS)
_PIC_REF = re.compile(r'^\.\./([a-z]+)/([^/\\]+)$')
_VID_REF = re.compile(r'^(?:\.\./)+assets/media/video/(\d+)\.([a-z0-9]+)$')
VIDEO_EXTS = ('mp4', 'webm', 'ogv')


def is_ref(value):
    return bool(value) and value.startswith('../')


def picture_ref(target_folder, src_folder, filename):
    """Value to store in a `target_folder` column for a picture that lives in
    `src_folder`: the bare name when it is the same folder."""
    return filename if src_folder == target_folder else f'../{src_folder}/{filename}'


def video_ref(video_id, ext):
    return f'../../../assets/media/video/{int(video_id)}.{ext}'


def library_video(database, video_id):
    """(path, ext) for a finished library video, or (None, None)."""
    table, idcol, filecol = MEDIA_KINDS['video']
    conn = sqlite3.connect(database)
    try:
        row = conn.execute(f"SELECT path, {filecol} FROM {table} "
                           f"WHERE {idcol} = ? AND dnLoadStatus = 3", (int(video_id),)).fetchone()
    finally:
        conn.close()
    if not row or not row[1]:
        return None, None
    full = os.path.join(row[0] or '', row[1])
    return full, (row[1].rsplit('.', 1)[-1].lower() if '.' in row[1] else '')


def resolve_path(root, database, target_folder, value):
    """Absolute file path for a stored value (bare name or reference), or
    None when the reference is malformed / points outside the whitelist."""
    if not value:
        return None
    m = _VID_REF.match(value)
    if m:
        path, ext = library_video(database, m.group(1))
        return path if path and ext == m.group(2) else None
    m = _PIC_REF.match(value)
    if m:
        folder, name = m.groups()
        if folder not in FOLDERS or name.startswith('.'):
            return None
        return os.path.join(root, 'static', 'uploads', folder, name)
    if is_ref(value) or '/' in value or '\\' in value:
        return None
    return os.path.join(root, 'static', 'uploads', target_folder, value)


def valid_ref(root, database, target_folder, value, kinds=('image', 'video')):
    """A reference the DM picked: well-formed, whitelisted, present on disk,
    and of an allowed kind."""
    if not is_ref(value):
        return False
    path = resolve_path(root, database, target_folder, value)
    if not path or not os.path.isfile(path):
        return False
    ext = value.rsplit('.', 1)[-1].lower() if '.' in value else ''
    kind = 'video' if ext in VIDEO_EXTS else 'image'
    return kind in kinds


def referenced_elsewhere(database, folder, filename, exclude=None):
    """True when some record OTHER than `exclude` points at this upload —
    by reference from another folder or by bare name within the same one.
    Scanned: character portraits, map backgrounds, monster stat images, and
    the OBS art settings. Exclude is (table, idcol, id) for the owner."""
    needles = (f'../{folder}/{filename}', f'/static/uploads/{folder}/{filename}')
    same = {'portraits': ('tblCharacters', 'character_id', 'portrait_path'),
            'battlemaps': ('tblBattleMaps', 'map_id', 'bg_image')}
    conn = sqlite3.connect(database)
    try:
        checks = [('tblCharacters', 'character_id', 'portrait_path'),
                  ('tblBattleMaps', 'map_id', 'bg_image'),
                  ('tblMonsterTemplates', 'template_id', 'stats_json'),
                  ('tblAppSettings', None, 'value')]
        for table, idcol, col in checks:
            try:
                rows = conn.execute(f"SELECT {idcol or 'NULL'}, {col} FROM {table} "
                                    f"WHERE {col} IS NOT NULL AND {col} != ''").fetchall()
            except sqlite3.OperationalError:
                continue
            for rid, val in rows:
                if exclude and exclude[0] == table and exclude[2] == rid:
                    continue
                val = str(val)
                if any(n in val for n in needles):
                    return True
                if folder in same and same[folder][0] == table and val == filename:
                    return True
    finally:
        conn.close()
    return False
