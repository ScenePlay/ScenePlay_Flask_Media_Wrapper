"""Metadata-extraction worker.

Independent of the download worker: it polls rows with metaStatus=1, runs
`yt-dlp --dump-single-json --skip-download` for the URL, and stores the
promoted columns plus a slim whitelist of the JSON (RAW_JSON_KEYS — the full
dump is ~175 KB/row of format tables nothing reads) in tblMediaMetadata,
filling the media row's displayName (only when blank) and duration.

IMPORTANT: the app installs a process-wide SIGCHLD reaper (app.py) that steals
child exit statuses, so subprocess return codes are unreliable here. We classify
purely on stdout (does it parse as JSON with an `id`?) and stderr text.
"""

import os
import json
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timedelta

import sql
from sql import (select_Meta_Que_Next, set_meta_status, upsert_media_metadata,
                 fill_display_name_if_empty, appsettingFlagGet, appsettingFlagUpdate,
                 meta_pending_any)
from thumbs import store as thumb_store

_START_DIR = os.path.dirname(os.path.realpath(__file__))
# pip-installed yt-dlp run as a module — no bash / no repo checkout, works on
# both OSes. Same JSON-on-stdout contract as the old yt-dlp.sh wrapper.
import ytdlp_source

_YTDLP_CMD = [sys.executable, '-m', 'yt_dlp']
# Suppress the console window each spawn would pop on Windows (0 is a no-op
# elsewhere — POSIX requires creationflags=0).
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0

MAX_RETRIES = 3
POLL_SECONDS = 2
EXTRACT_TIMEOUT = 120

# Substrings (checked lowercased) that mean "this will never succeed" — don't retry.
_PERMANENT_MARKERS = (
    'private video', 'video unavailable', 'video is unavailable',
    'this video is not available', 'no longer available', 'has been removed',
    'removed by the uploader', 'account associated with this video has been terminated',
    'members-only', 'join this channel', 'sign in to confirm your age',
    'age-restricted', 'inappropriate for some users',
    'available in your country', 'blocked it in your country',
    'deleted video', 'unavailable video', 'this channel does not exist',
)


def classify_error(stderr):
    """'permanent' if stderr names an unrecoverable condition, else 'transient'."""
    low = (stderr or '').lower()
    return 'permanent' if any(m in low for m in _PERMANENT_MARKERS) else 'transient'


def extract_metadata(url):
    """Return ('ok', info_dict) | ('permanent', err) | ('transient', err).

    Classification never trusts returncode (SIGCHLD reaper) — success == stdout
    parses to a JSON object carrying an `id`."""
    try:
        proc = subprocess.run(
            _YTDLP_CMD + ['--dump-single-json', '--skip-download',
                          '--no-playlist', '--no-warnings', url],
            capture_output=True, text=True, timeout=EXTRACT_TIMEOUT,
            creationflags=_NO_WINDOW, env=ytdlp_source.popen_env())
    except subprocess.TimeoutExpired:
        return 'transient', 'extraction timed out'
    except Exception as e:  # pragma: no cover - spawn failure
        return 'transient', f'spawn failed: {e}'

    out = (proc.stdout or '').strip()
    if out:
        try:
            info = json.loads(out)
            if isinstance(info, dict) and info.get('id'):
                return 'ok', info
        except ValueError:
            pass
    return classify_error(proc.stderr), (proc.stderr or 'no output').strip()[:500]


def _promoted_fields(info):
    """Pick the columns we surface out of the full yt-dlp JSON."""
    return {
        'title':       info.get('title'),
        'duration':    info.get('duration'),
        'uploader':    info.get('uploader') or info.get('channel'),
        'upload_date': info.get('upload_date'),
        'thumbnail':   info.get('thumbnail'),
        'view_count':  info.get('view_count'),
        'description': info.get('description'),
        'categories':  json.dumps(info.get('categories') or []),
    }


# Info-dict keys worth persisting in raw_json beyond the promoted columns:
# identity/provenance, attribution, playability flags, music tagging, chapter
# marks. The full dump averaged ~175 KB per row — mostly `formats` with per-
# variant fragment URLs and HTTP headers — and nothing ever read it back.
# Migration 0002 slims pre-existing rows to this same shape; keep the two
# lists in sync if this ever grows.
RAW_JSON_KEYS = (
    'id', 'webpage_url', 'extractor',
    'channel', 'channel_id', 'uploader_id',
    'tags', 'like_count', 'comment_count', 'average_rating',
    'age_limit', 'availability', 'live_status',
    'album', 'artist', 'track', 'release_year',
    'chapters',
)


def slim_raw_json(info):
    """The whitelisted subset of a yt-dlp info dict, as JSON (a few KB)."""
    return json.dumps({k: info[k] for k in RAW_JSON_KEYS if info.get(k) is not None})


def _handle_job(pkey, url, media_type, retry_count):
    set_meta_status(media_type, pkey, 2)   # Processing
    try:
        _run_job(pkey, url, media_type, retry_count)
    except Exception:
        # Any unexpected error after status 2 was committed (e.g. sqlite
        # "database is locked" past the busy-timeout) would otherwise strand the
        # row at 2 forever — select_Meta_Que_Next only picks status 1. Put it
        # back in the queue; app boot also sweeps 2→1 for hard crashes.
        set_meta_status(media_type, pkey, 1)
        raise


def _run_job(pkey, url, media_type, retry_count):
    status, payload = extract_metadata(url)
    now = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')

    if status == 'ok':
        info = payload
        fields = _promoted_fields(info)
        fields['raw_json'] = slim_raw_json(info)[:2_000_000]   # guard against absurd blobs
        fields['retry_count'] = retry_count
        fields['last_error'] = ''
        fields['extracted_at'] = now
        upsert_media_metadata(media_type, pkey, fields)
        if info.get('title'):
            fill_display_name_if_empty(media_type, pkey, info['title'])
        thumb_store.cache(media_type, pkey, info.get('thumbnail'))   # best-effort
        set_meta_status(media_type, pkey, 3)   # Finished
        return

    # failure — record retry_count/last_error so the queue can compute backoff
    new_retries = retry_count + 1
    upsert_media_metadata(media_type, pkey, {
        'retry_count': new_retries, 'last_error': payload, 'extracted_at': now})

    if status == 'permanent':
        set_meta_status(media_type, pkey, 5)   # Unavailable — never retried
    elif new_retries < MAX_RETRIES:
        backoff = datetime.utcnow() + timedelta(minutes=2 ** new_retries)
        set_meta_status(media_type, pkey, 1, backoff.strftime('%Y-%m-%d %H:%M:%S'))
    else:
        set_meta_status(media_type, pkey, 4)   # Failed (retries exhausted)


# --- thumbnail backfill -----------------------------------------------------
# Rows extracted before local caching existed have a remote URL but no file in
# static/thumbs. The threader fills them in gently: ONE download per poll tick
# (2s), independent of the extraction switch. URLs that fail stay skipped for
# the life of the process; once a full scan finds nothing missing, the next
# scan waits THUMB_RESCAN_SECONDS.
THUMB_RESCAN_SECONDS = 600
_thumb_next_scan = 0.0
_thumb_failed = set()


def backfill_one_thumbnail():
    """Cache at most one missing local thumbnail. Returns True if it did."""
    global _thumb_next_scan
    if time.time() < _thumb_next_scan:
        return False
    conn = sqlite3.connect(sql.database)
    try:
        rows = conn.execute(
            "SELECT media_type, media_id, thumbnail FROM tblMediaMetadata "
            "WHERE thumbnail IS NOT NULL AND thumbnail <> ''").fetchall()
    finally:
        conn.close()
    for media_type, media_id, remote_url in rows:
        key = (media_type, media_id)
        if key in _thumb_failed or thumb_store.exists(media_type, media_id):
            continue
        if not thumb_store.cache(media_type, media_id, remote_url):
            _thumb_failed.add(key)
        return True
    _thumb_next_scan = time.time() + THUMB_RESCAN_SECONDS
    return False


def MetaQue_threader():
    while True:
        time.sleep(POLL_SECONDS)
        if os.getppid() == 1:      # parent died → don't linger as an orphan
            break
        try:
            backfill_one_thumbnail()
            if str(appsettingFlagGet('meta_que_switch') or '0') != '1':
                continue
            jobs = select_Meta_Que_Next()
            if not jobs:
                # Only go idle when NOTHING is pending. The selector excludes
                # rows in retry backoff, so switching off on an empty select
                # would strand them: nothing re-raises the switch when their
                # timer expires. Keep polling until they run or the queue is
                # genuinely empty.
                if not meta_pending_any():
                    appsettingFlagUpdate('meta_que_switch', 0)   # idle until next enqueue
                continue
            pkey, url, media_type, retry_count = jobs[0][0], jobs[0][1], jobs[0][2], jobs[0][3]
            _handle_job(pkey, url, media_type, retry_count or 0)
        except Exception as e:      # one bad row must never kill the loop
            print('[meta_que] iteration error:', e)
