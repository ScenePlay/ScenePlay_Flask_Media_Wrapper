"""YouTube URL / video-ID helpers.

Pure functions, no Flask/blueprint imports, so background workers
(meta_que.py, playlist_que.py) can import this without dragging in the
web stack. The canonical video ID is what makes dedup work: the same
video reached via different URL forms resolves to one 11-char ID.
"""

import re
from urllib.parse import urlparse, parse_qs

# A YouTube video ID is exactly 11 chars of [A-Za-z0-9_-] — and CAN start with
# '-' (~1.6% of videos), which is why downstream shell handling must be dash-safe.
_ID_RE = re.compile(r'^[A-Za-z0-9_-]{11}$')

# Path-style forms where the ID is the first path segment after a marker.
_PATH_MARKERS = ('shorts', 'embed', 'live', 'v')


def _valid(vid):
    return vid if vid and _ID_RE.match(vid) else None


def youtube_video_id(url):
    """Extract the canonical 11-char video ID from any common YouTube URL form,
    or None. Primary form is the `v=` query param (watch?v=<id>); parsed with
    urlparse so trailing params like &list= / &t= never leak into the ID."""
    if not url:
        return None
    url = url.strip()
    # A bare ID passed straight through.
    if _ID_RE.match(url):
        return url
    try:
        parts = urlparse(url if '//' in url else 'https://' + url)
    except ValueError:
        return None

    host = (parts.hostname or '').lower().replace('www.', '')

    # watch?v=<id>  (the dominant form, e.g. youtube.com/watch?v=IzOx0X5FWrc)
    qs = parse_qs(parts.query)
    if 'v' in qs and qs['v']:
        vid = _valid(qs['v'][0])
        if vid:
            return vid

    segs = [s for s in parts.path.split('/') if s]

    # youtu.be/<id>
    if host == 'youtu.be' and segs:
        return _valid(segs[0])

    # youtube.com/shorts/<id>, /embed/<id>, /live/<id>, /v/<id>
    if segs and segs[0].lower() in _PATH_MARKERS and len(segs) >= 2:
        return _valid(segs[1])

    return None


def canonical_watch_url(vid):
    """The one URL form we store in urlSource, so dedup + downloads are stable
    and a stray &list= can never make yt-dlp iterate a whole playlist."""
    return f'https://www.youtube.com/watch?v={vid}'


def is_playlist_url(url):
    """True for a playlist the user wants EXPANDED — a `list=` with NO
    identifiable single video. Any URL carrying a video id (watch?v=X&list=Y,
    youtu.be/X?list=Y, shorts/X?list=Y) is treated as that single video: the
    user shared a specific video that merely happens to sit in a playlist."""
    if not url:
        return False
    try:
        parts = urlparse(url if '//' in url else 'https://' + url)
    except ValueError:
        return False
    qs = parse_qs(parts.query)
    return 'list' in qs and youtube_video_id(url) is None
