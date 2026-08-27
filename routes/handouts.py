"""PDF handouts: upload any PDF to the box and read it in a page-turning
viewer (Utilities → Handouts).

Files land under static/uploads/handouts/<uuid>.pdf so they ride along with
Backup → Restore like every other upload folder; rows live in tblHandouts
(models/ttrpg.py). Rendering is entirely client-side (vendored pdf.js in
static/scripts/pdfjs/ + static/scripts/handout_reader.js) — no server-side
PDF parser, so the page count is reported back by the viewer the first time
a document opens. Everything here is DM-only, like the rest of Utilities.
"""
import os
import re
import uuid

from flask import (Blueprint, abort, current_app, flash, jsonify, redirect,
                   render_template, request, send_from_directory, url_for)
from flask_login import login_required

from extensions import db
from models.ttrpg import tblHandouts
from routes._util import _now
from routes.auth import dm_required

handouts_bp = Blueprint('handouts_bp', __name__, url_prefix='/handouts')

UPLOAD_FOLDER = os.path.join('static', 'uploads', 'handouts')
# Rulebooks run 50-100 MB; bigger than this is almost certainly a mistake
# (and would take a Pi minutes to accept). Reverse proxies cap uploads too —
# scripts/setup mentions the nginx client_max_body_size fix.
MAX_PDF_BYTES = 300 * 1024 * 1024
TITLE_MAX = 120
FILENAME_RE = re.compile(r'^[0-9a-f]{32}\.pdf$')


def _upload_dir():
    return os.path.join(current_app.root_path, UPLOAD_FOLDER)


def _file_path(row):
    return os.path.join(_upload_dir(), row.filename)


def _clean_title(raw, fallback):
    title = re.sub(r'\s+', ' ', str(raw or '')).strip()
    if not title:
        title = fallback
    return title[:TITLE_MAX]


def _title_from_filename(name):
    base = os.path.splitext(os.path.basename(str(name or '')))[0]
    base = re.sub(r'[_\-]+', ' ', base).strip()
    return base or 'Untitled handout'


def _human_size(n):
    n = float(n or 0)
    for unit in ('B', 'KB', 'MB', 'GB'):
        if n < 1024 or unit == 'GB':
            return f'{n:.0f} {unit}' if unit == 'B' else f'{n:.1f} {unit}'
        n /= 1024


def _row_view(row):
    return {
        'id': row.handout_id,
        'title': row.title,
        'filename': row.filename,
        'size_h': _human_size(row.size_bytes),
        'page_count': row.page_count,
        'last_page': row.last_page or 1,
        'created_at': row.created_at,
        'on_disk': os.path.isfile(_file_path(row)),
    }


@handouts_bp.route('/')
@login_required
@dm_required
def index():
    # base.html's player bar wants the queue stats + volume like every page
    from extensions import currentvolume
    from sql import select_data_stats
    rows = tblHandouts.query.order_by(tblHandouts.title.collate('NOCASE')).all()
    return render_template('handouts.html', handouts=[_row_view(r) for r in rows],
                           max_mb=MAX_PDF_BYTES // (1024 * 1024),
                           items=select_data_stats(), volume=currentvolume())


def _save_pdf(f, title):
    """Validate + store an uploaded PDF. Returns (row, error)."""
    if f is None or not f.filename:
        return None, 'choose a PDF file'
    head = f.stream.read(5)
    f.stream.seek(0)
    # The magic number is the real check; the extension is just a hint.
    if not head.startswith(b'%PDF'):
        return None, 'that file is not a PDF'
    raw = f.read()
    if len(raw) > MAX_PDF_BYTES:
        return None, f'PDF is larger than {MAX_PDF_BYTES // (1024 * 1024)} MB'
    if not raw:
        return None, 'empty file'
    filename = f'{uuid.uuid4().hex}.pdf'
    dest = _upload_dir()
    os.makedirs(dest, exist_ok=True)
    with open(os.path.join(dest, filename), 'wb') as out:
        out.write(raw)
    row = tblHandouts(title=_clean_title(title, _title_from_filename(f.filename)),
                      filename=filename, size_bytes=len(raw), last_page=1,
                      created_at=_now())
    db.session.add(row)
    db.session.commit()
    return row, None


@handouts_bp.route('/upload', methods=['POST'])
@login_required
@dm_required
def upload():
    row, err = _save_pdf(request.files.get('pdf'), request.form.get('title'))
    wants_json = request.accept_mimetypes.best == 'application/json' \
        or request.args.get('format') == 'json'
    if err:
        if wants_json:
            return jsonify({'ok': False, 'error': err}), 400
        flash(f'Upload failed: {err}')
        return redirect(url_for('handouts_bp.index'))
    if wants_json:
        return jsonify({'ok': True, 'handout': _row_view(row)})
    return redirect(url_for('handouts_bp.index'))


@handouts_bp.route('/<int:handout_id>/rename', methods=['POST'])
@login_required
@dm_required
def rename(handout_id):
    row = db.session.get(tblHandouts, handout_id)
    if row is None:
        return jsonify({'ok': False, 'error': 'not found'}), 404
    data = request.get_json(silent=True) or request.form
    row.title = _clean_title(data.get('title'), row.title)
    row.updated_at = _now()
    db.session.commit()
    return jsonify({'ok': True, 'title': row.title})


@handouts_bp.route('/<int:handout_id>/delete', methods=['POST'])
@login_required
@dm_required
def delete(handout_id):
    row = db.session.get(tblHandouts, handout_id)
    if row is None:
        return jsonify({'ok': False, 'error': 'not found'}), 404
    try:
        if os.path.isfile(_file_path(row)):
            os.remove(_file_path(row))
    except OSError:
        pass
    db.session.delete(row)
    db.session.commit()
    if request.is_json or request.args.get('format') == 'json':
        return jsonify({'ok': True})
    return redirect(url_for('handouts_bp.index'))


@handouts_bp.route('/<int:handout_id>/file')
@login_required
@dm_required
def file(handout_id):
    """The PDF bytes. Served through the guard (not as a bare static URL) so
    a handout is never readable without a DM session; inline so pdf.js can
    fetch it and a plain browser tab can still open it."""
    row = db.session.get(tblHandouts, handout_id)
    if row is None or not FILENAME_RE.match(row.filename):
        abort(404)
    if not os.path.isfile(_file_path(row)):
        abort(404)
    return send_from_directory(_upload_dir(), row.filename,
                               mimetype='application/pdf',
                               as_attachment=request.args.get('dl') == '1',
                               download_name=f'{row.title}.pdf',
                               conditional=True)


@handouts_bp.route('/<int:handout_id>/read')
@login_required
@dm_required
def read(handout_id):
    row = db.session.get(tblHandouts, handout_id)
    if row is None:
        abort(404)
    if not os.path.isfile(_file_path(row)):
        flash(f'"{row.title}" is missing on disk — restore it or upload again.')
        return redirect(url_for('handouts_bp.index'))
    return render_template('handout_read.html', handout=_row_view(row))


@handouts_bp.route('/<int:handout_id>/progress', methods=['POST'])
@login_required
@dm_required
def progress(handout_id):
    """Reader state from the viewer: {page, page_count}. Page is clamped to
    the known count so a stale tab can't park the bookmark off the end."""
    row = db.session.get(tblHandouts, handout_id)
    if row is None:
        return jsonify({'ok': False, 'error': 'not found'}), 404
    data = request.get_json(silent=True) or {}
    try:
        count = int(data.get('page_count') or 0)
    except (TypeError, ValueError):
        count = 0
    if count > 0:
        row.page_count = count
    try:
        page = int(data.get('page') or 0)
    except (TypeError, ValueError):
        page = 0
    if page > 0:
        if row.page_count:
            page = min(page, row.page_count)
        row.last_page = page
    row.updated_at = _now()
    db.session.commit()
    return jsonify({'ok': True, 'last_page': row.last_page,
                    'page_count': row.page_count})
