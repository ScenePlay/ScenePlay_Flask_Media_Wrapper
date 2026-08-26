"""Groupings derived from the yt-dlp metadata we already store.

- ARTIST: YouTube has no artist field for ordinary uploads. Sources, best
  first: the `artist` field on "- Topic" auto-uploads (exact); an
  "Artist - Title" title whose artist matches the channel (high); the title
  alone (medium); the cleaned channel name (low). suggest_artists() shows
  the derivation so the DM can confirm; meta_que auto-fills only the exact/
  high cases for new downloads.
- KIND by duration: song / long track / mix-ambience — a 4-hour dungeon
  loop behaves differently from a 3-minute track when building scenes.
- DECADE: release_year (Topic uploads) or a year in the title; upload_date
  is deliberately NOT used — it says when the video hit YouTube.

Pure module (sqlite only); stored on tblMediaMetadata.artist/artist_source.
"""
import json
import re
import sqlite3

_TITLE_RX = re.compile(r'^\s*(.{1,60}?)\s+[-–—|:]\s+(.+?)\s*$')
_NOISE_RX = re.compile(r'\s*[\(\[][^\)\]]*(official|video|audio|lyric|hd|hq|remaster|visualizer|4k|live|version)[^\)\]]*[\)\]]', re.I)
_CHANNEL_NOISE = re.compile(r'\s*(-\s*topic|vevo|official|officialvideos|music|tv|channel|records)\s*$', re.I)
_YEAR_RX = re.compile(r'\b(19[2-9]\d|20[0-2]\d)\b')

KINDS = {'song': 'Song', 'long': 'Long track', 'mix': 'Mix / ambience'}


def clean_channel(name):
    n = (name or '').strip()
    for _ in range(3):
        n2 = _CHANNEL_NOISE.sub('', n).strip()
        if n2 == n:
            break
        n = n2
    return n


def clean_title(title):
    t = (title or '')
    for _ in range(3):
        t2 = _NOISE_RX.sub('', t)
        if t2 == t:
            break
        t = t2
    return t.strip()


def _norm(s):
    return re.sub(r'[^a-z0-9]', '', (s or '').lower())


def derive_artist(title, channel, info=None):
    """(artist, source, confidence) — confidence: exact | high | medium | low | none."""
    info = info or {}
    if info.get('artist'):
        return str(info['artist']).split(',')[0].strip(), 'topic', 'exact'
    chan = clean_channel(channel)
    m = _TITLE_RX.match(clean_title(title))
    if m:
        cand = m.group(1).strip().strip('"\'')
        # "Title - Artist" also exists (jazz uploads); prefer whichever side matches the channel
        other = m.group(2).strip()
        if chan and _norm(chan) and _norm(chan) in _norm(other) and _norm(chan) not in _norm(cand):
            cand = other
        if chan and _norm(chan) and (_norm(chan) in _norm(cand) or _norm(cand) in _norm(chan)):
            return cand, 'title+channel', 'high'
        if len(cand) >= 2 and not _YEAR_RX.fullmatch(cand):
            return cand, 'title', 'medium'
    if chan and not channel.strip().lower().endswith('- topic'):
        return chan, 'channel', 'low'
    return '', '', 'none'


def media_kind(duration):
    try:
        d = int(duration or 0)
    except (TypeError, ValueError):
        return ''
    if d <= 0:
        return ''
    return 'song' if d < 8 * 60 else 'long' if d < 30 * 60 else 'mix'


def decade(info=None, title=''):
    info = info or {}
    y = info.get('release_year')
    if not y:
        m = _YEAR_RX.search(title or '')
        y = m.group(1) if m else None
    try:
        y = int(y)
    except (TypeError, ValueError):
        return ''
    return f'{y // 10 * 10}s'


def suggest_artists(database, only_unset=True):
    """[{media_type, id, name, channel, artist, current, source, confidence,
    kind, decade}] for music and video rows with metadata."""
    conn = sqlite3.connect(database)
    out = []
    try:
        for kind, tbl, pk, namecol in (('music', 'tblMusic', 'song_id', 'song'),
                                       ('video', 'tblVideoMedia', 'video_ID', 'title')):
            rows = conn.execute(
                f"SELECT m.{pk}, COALESCE(m.displayName,''), COALESCE(d.title,''), COALESCE(d.uploader,''), "
                f"COALESCE(d.artist,''), d.duration, d.raw_json FROM {tbl} m "
                f"JOIN tblMediaMetadata d ON d.media_type=? AND d.media_id=m.{pk} "
                + ("WHERE COALESCE(d.artist,'') = '' " if only_unset else '') +
                f"ORDER BY m.{pk}", (kind,)).fetchall()
            for rid, disp, title, chan, cur, dur, raw in rows:
                try:
                    info = json.loads(raw or '{}') if raw else {}
                except ValueError:
                    info = {}
                artist, src, conf = derive_artist(title or disp, chan, info)
                out.append({'media_type': kind, 'id': rid, 'name': disp or title, 'channel': chan,
                            'current': cur, 'artist': artist, 'source': src, 'confidence': conf,
                            'kind': media_kind(dur), 'decade': decade(info, title)})
    finally:
        conn.close()
    return out


def apply_artists(database, choices):
    """choices: [{media_type, id, artist}] — writes tblMediaMetadata.artist
    (source 'dm'); '' clears. Returns the number of rows changed."""
    conn = sqlite3.connect(database)
    n = 0
    try:
        for ch in choices:
            kind = ch.get('media_type')
            try:
                rid = int(ch.get('id'))
            except (TypeError, ValueError):
                continue
            if kind not in ('music', 'video'):
                continue
            artist = (ch.get('artist') or '').strip()[:120]
            cur = conn.execute("UPDATE tblMediaMetadata SET artist=?, artist_source=? "
                               "WHERE media_type=? AND media_id=?",
                               (artist, 'dm' if artist else '', kind, rid))
            n += cur.rowcount
        conn.commit()
    finally:
        conn.close()
    return n
