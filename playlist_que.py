"""Playlist-expansion worker.

Polls tblPlaylistQueue, runs `yt-dlp --flat-playlist -J` to list a playlist's
entries WITHOUT downloading each, and funnels every live entry through the
shared enqueue_single() intake (so dedup applies per entry). Dead entries
(private/deleted) are skipped rather than enqueued as guaranteed failures.

Like meta_que, classification never trusts subprocess return codes (the app's
SIGCHLD reaper eats them) — success == stdout parses to JSON with entries.
"""

import os
import json
import subprocess
import time

from sql import (select_Playlist_Que_Next, update_playlist_status, enqueue_single,
                 appsettingFlagGet, appsettingFlagUpdate)
from ytid import canonical_watch_url

_START_DIR = os.path.dirname(os.path.realpath(__file__))
_YTDLP = os.path.join(_START_DIR, 'yt-dlp', 'yt-dlp.sh')

MAX_RETRIES = 3
POLL_SECONDS = 2
EXPAND_TIMEOUT = 180

# flat-playlist marks unwatchable entries by these availability/title flags.
_DEAD_TITLES = ('[private video]', '[deleted video]', '[unavailable video]')


def _entry_is_dead(entry):
    avail = (entry.get('availability') or '').lower()
    if avail in ('private', 'needs_auth', 'unlisted') and not entry.get('id'):
        return True
    title = (entry.get('title') or '').lower()
    return title in _DEAD_TITLES


def expand_playlist(url):
    """Return ('ok', [entries]) | ('transient', err). Each entry is the raw
    flat-playlist dict; callers use entry['id']."""
    try:
        proc = subprocess.run(
            ['bash', _YTDLP, '--flat-playlist', '-J', '--no-warnings', url],
            capture_output=True, text=True, timeout=EXPAND_TIMEOUT)
    except subprocess.TimeoutExpired:
        return 'transient', 'playlist expansion timed out'
    except Exception as e:  # pragma: no cover
        return 'transient', f'spawn failed: {e}'

    out = (proc.stdout or '').strip()
    if out:
        try:
            info = json.loads(out)
            if isinstance(info, dict):
                return 'ok', info.get('entries') or []
        except ValueError:
            pass
    return 'transient', (proc.stderr or 'no output').strip()[:500]


def _handle_job(playlist_id, url, media_type, scene_ID, retry_count):
    update_playlist_status(playlist_id, 2)   # Processing
    try:
        _run_job(playlist_id, url, media_type, scene_ID, retry_count)
    except Exception:
        # Don't strand the job at status 2 (select_Playlist_Que_Next only picks
        # status 1); re-queue it. App boot also sweeps 2→1 for hard crashes.
        update_playlist_status(playlist_id, 1)
        raise


def _run_job(playlist_id, url, media_type, scene_ID, retry_count):
    status, payload = expand_playlist(url)

    if status != 'ok':
        new_retries = (retry_count or 0) + 1
        if new_retries < MAX_RETRIES:
            update_playlist_status(playlist_id, 1, retry_count=new_retries, last_error=payload)
        else:
            update_playlist_status(playlist_id, 4, retry_count=new_retries, last_error=payload)
        return

    mediaType = 'mp3' if media_type == 'music' else 'mp4'
    added = 0
    for entry in payload:
        if _entry_is_dead(entry):
            continue
        vid = entry.get('id')
        if not vid:
            continue
        try:
            enqueue_single(canonical_watch_url(vid), mediaType, scene_ID)
            added += 1
        except Exception as e:      # a single bad entry must not abort the batch
            print('[playlist_que] entry error:', vid, e)
    update_playlist_status(playlist_id, 3, last_error=f'expanded {added} entries')


def PlaylistQue_threader():
    while True:
        time.sleep(POLL_SECONDS)
        if os.getppid() == 1:
            break
        try:
            if str(appsettingFlagGet('playlist_que_switch') or '0') != '1':
                continue
            jobs = select_Playlist_Que_Next()
            if not jobs:
                appsettingFlagUpdate('playlist_que_switch', 0)
                continue
            playlist_id, url, media_type, scene_ID, retry_count = jobs[0]
            _handle_job(playlist_id, url, media_type, scene_ID, retry_count or 0)
        except Exception as e:
            print('[playlist_que] iteration error:', e)
