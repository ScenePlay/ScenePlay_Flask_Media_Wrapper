"""Asset inventory for the Utilities → Downloads page.

Pure module (no Flask): lists what's actually on disk for music, video and
the uploaded pictures, joined to the metadata the app knows about them, so
the DM can pull files off the box one at a time or as a zip.

Music/video rows come from tblMusic / tblVideoMedia (finished downloads
only) joined to tblMediaMetadata — the yt-dlp title/uploader/duration is the
primary identity; the typed displayName and then the filename are fallbacks.
Pictures are whatever sits under static/uploads/<folder>/, with the record
that references each file (map, character, monster) where one exists.
"""
import os
import sqlite3
import zipfile

# Upload folders offered for download, with a human label.
PICTURE_FOLDERS = (
    ('battlemaps', 'Battle map art'),
    ('portraits',  'Character portraits'),
    ('monsters',   'Monster images'),
    ('obs',        'OBS show cards'),
    ('textures',   '3D textures'),
    ('weapons',    'Weapon images'),
    ('armor',      'Armor images'),
)
MEDIA_KINDS = {
    'music': ('tblMusic', 'song_id', 'song'),
    'video': ('tblVideoMedia', 'video_ID', 'title'),
}


def fmt_size(n):
    if n is None:
        return ''
    for unit in ('B', 'KB', 'MB', 'GB'):
        if n < 1024 or unit == 'GB':
            return f'{n:.0f} {unit}' if unit == 'B' else f'{n:.1f} {unit}'
        n /= 1024.0
    return ''


def fmt_duration(secs):
    try:
        s = int(secs or 0)
    except (TypeError, ValueError):
        return ''
    if s <= 0:
        return ''
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    return f'{h}:{m:02d}:{s:02d}' if h else f'{m}:{s:02d}'


def _stat(path):
    try:
        st = os.stat(path)
        return st.st_size, st.st_mtime
    except OSError:
        return None, None


def media_rows(database, kind):
    """Finished downloads of one kind, newest id first.

    Each row: id, file, dir, path, exists, size, size_h, display_name, title,
    uploader, duration, duration_h, upload_date, name (the primary label)."""
    table, idcol, filecol = MEDIA_KINDS[kind]
    conn = sqlite3.connect(database)
    try:
        rows = conn.execute(
            f"SELECT m.{idcol}, m.path, m.{filecol}, m.displayName, "
            f"       d.title, d.uploader, d.duration, d.upload_date "
            f"FROM {table} m "
            f"LEFT JOIN tblMediaMetadata d ON d.media_type = ? AND d.media_id = m.{idcol} "
            f"       AND COALESCE(d.active, 1) = 1 "
            f"WHERE m.dnLoadStatus = 3 AND m.{filecol} IS NOT NULL AND m.{filecol} != '' "
            f"ORDER BY m.{idcol} DESC", (kind,)).fetchall()
    finally:
        conn.close()
    out = []
    for mid, mdir, fname, disp, title, uploader, dur, udate in rows:
        mdir = mdir or ''
        full = os.path.join(mdir, fname)
        size, mtime = _stat(full)
        out.append({
            'id': mid, 'file': fname, 'dir': mdir, 'path': full,
            'exists': size is not None, 'size': size, 'size_h': fmt_size(size),
            'display_name': disp or '', 'title': title or '',
            'uploader': uploader or '', 'duration': dur,
            'duration_h': fmt_duration(dur), 'upload_date': udate or '',
            'name': (title or disp or fname),
        })
    return out


def _used_by(database):
    """{(folder, filename): label} for files a record references."""
    used = {}
    conn = sqlite3.connect(database)
    try:
        for sql, folder in (
                ("SELECT name, bg_image FROM tblBattleMaps WHERE bg_image != ''", 'battlemaps'),
                ("SELECT name, portrait_path FROM tblCharacters WHERE portrait_path != ''", 'portraits'),
                ("SELECT name, image_url FROM tblMonsterTemplates WHERE image_url != ''", 'monsters')):
            try:
                for name, ref in conn.execute(sql):
                    if ref:
                        used[(folder, os.path.basename(str(ref)))] = name
            except sqlite3.OperationalError:
                pass    # table absent (scratch db / old schema)
    finally:
        conn.close()
    return used


def picture_rows(database, uploads_dir):
    """Every file under the known upload folders: folder, folder_label, file,
    path, size, size_h, used_by, mtime."""
    used = _used_by(database)
    out = []
    for folder, label in PICTURE_FOLDERS:
        d = os.path.join(uploads_dir, folder)
        if not os.path.isdir(d):
            continue
        for fname in sorted(os.listdir(d), key=str.lower):
            full = os.path.join(d, fname)
            if not os.path.isfile(full) or fname.startswith('.'):
                continue
            size, mtime = _stat(full)
            out.append({'folder': folder, 'folder_label': label, 'file': fname,
                        'path': full, 'size': size, 'size_h': fmt_size(size),
                        'used_by': used.get((folder, fname), ''), 'mtime': mtime})
    return out


def totals(rows):
    present = [r for r in rows if r.get('size') is not None]
    return {'count': len(present), 'missing': len(rows) - len(present),
            'bytes': sum(r['size'] for r in present),
            'bytes_h': fmt_size(sum(r['size'] for r in present))}


def safe_picture_ref(folder, name):
    """True for a folder we serve and a bare filename (no path tricks)."""
    return (folder in {f for f, _ in PICTURE_FOLDERS}
            and bool(name) and name == os.path.basename(name)
            and not name.startswith('.'))


class _Drain:
    """Unseekable write target for zipfile: collects chunks for a generator."""
    def __init__(self):
        self.chunks = []
        self.pos = 0

    def write(self, b):
        self.chunks.append(bytes(b))
        self.pos += len(b)
        return len(b)

    def tell(self):
        return self.pos

    def flush(self):
        pass

    def take(self):
        out, self.chunks = self.chunks, []
        return out


def zip_stream(entries):
    """Yield the bytes of a ZIP (stored, no recompression — media is already
    compressed) containing (arcname, path) pairs, without buffering the
    whole archive. Unseekable-stream mode: zipfile writes data descriptors.
    Names are de-duplicated so two files with the same title both land."""
    drain = _Drain()
    seen = set()
    with zipfile.ZipFile(drain, 'w', zipfile.ZIP_STORED, allowZip64=True) as zf:
        for arcname, path in entries:
            base, ext = os.path.splitext(arcname)
            n, candidate = 1, arcname
            while candidate.lower() in seen:
                n += 1
                candidate = f'{base} ({n}){ext}'
            seen.add(candidate.lower())
            try:
                with open(path, 'rb') as src, zf.open(candidate, 'w', force_zip64=True) as dst:
                    while True:
                        chunk = src.read(1024 * 1024)
                        if not chunk:
                            break
                        dst.write(chunk)
                        for c in drain.take():
                            yield c
            except OSError:
                continue        # vanished since listing — skip, keep going
            for c in drain.take():
                yield c
    for c in drain.take():
        yield c


def arc_name(row, kind):
    """Zip entry name for a media row: the metadata title as the filename,
    the real extension kept, filesystem-unfriendly characters scrubbed."""
    ext = os.path.splitext(row['file'])[1]
    label = row['name'] or os.path.splitext(row['file'])[0]
    clean = ''.join(ch if ch not in '\\/:*?"<>|' else '_' for ch in label).strip() or 'media'
    return f'{kind}/{clean[:120]}{ext}'
