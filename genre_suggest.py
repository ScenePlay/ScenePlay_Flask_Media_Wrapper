"""Suggest a genre for every song that has none, from what the box already
knows — then let the DM confirm before anything is written.

Two signals, in order of trust:

1. SCENE MEMBERSHIP. Scenes named after genres ("Rock", "Jazz", "Coffee
   Jazz", "Classical", "Best of the 80's") are how the library was actually
   curated; a song in one of them is that genre with near certainty. The
   scene→genre mapping is DATA: SCENE_MAP below seeds it, the DM's edits
   live in the 'genre_scene_map' app setting (JSON), and any scene whose
   name matches a lutGenre name maps to it automatically.
2. YT-DLP TAGS / TITLE / CHANNEL / DESCRIPTION. Keyword rules (TAG_RULES,
   also data) give a second opinion: a sub-genre where the scene is silent,
   and a "these disagree" flag for review where it isn't. Tags alone are
   noisy (an "80s pop" video also says "rock"), so they never outrank a
   scene.

Every suggestion carries its reason so a review page can show WHY, and
apply() only ever writes rows the DM confirmed. Pure module: sqlite only.
"""
import json
import re
import sqlite3

# Seed scene→genre mapping (lower-cased scene name). Editable via the
# 'genre_scene_map' setting; a scene named exactly like a genre needs no row.
SCENE_MAP = {
    'rock': 'Rock', 'jazz': 'Jazz', 'coffee jazz': 'Jazz', 'classical': 'Classical',
    "best of the 80's": 'Pop', 'best of the 80s': 'Pop', '80s': 'Pop',
    'tavern': 'Soundtrack', 'boss battle': 'Soundtrack', 'combat': 'Soundtrack',
    'fight': 'Soundtrack', 'explore': 'Soundtrack',
}
# Keyword rules over tags/title/channel/description, checked in order; the
# FIRST genre whose keywords hit in the most specific field wins.
TAG_RULES = [
    ('Jazz',       ['jazz', 'swing', 'bebop', 'bossa nova', 'big band']),
    ('Classical',  ['classical', 'chopin', 'beethoven', 'mozart', 'bach', 'debussy', 'symphony',
                    'concerto', 'nocturne', 'sonata', 'orchestra', 'piano cover']),
    ('Blues',      ['blues']),
    ('Soul',       ['soul', 'funk', 'motown', 'r&b']),
    ('Hip-Hop',    ['hip hop', 'hiphop', 'rap']),
    ('Country',    ['country', 'bluegrass']),
    ('Electronic', ['synthwave', 'electronic', 'edm', 'techno', 'house music', 'lo-fi', 'lofi', 'chillhop']),
    ('Folk',       ['folk', 'acoustic', 'celtic']),
    ('Soundtrack', ['ambient', 'soundtrack', 'dungeon', 'tavern', 'd&d', 'dnd', 'ttrpg', 'fantasy music',
                    'medieval', 'battle music', 'epic music', 'combat music']),
    ('Pop',        ['pop', '80s', 'synthpop', 'new wave']),
    ('Rock',       ['rock', 'metal', 'punk', 'grunge']),
]
FIELD_ORDER = ('tags', 'title', 'channel', 'description')


def scene_map(get):
    """Effective scene→genre mapping: seed overlaid by the DM's saved JSON."""
    m = dict(SCENE_MAP)
    try:
        raw = get('genre_scene_map', '') or ''
        if raw:
            for k, v in json.loads(raw).items():
                if v:
                    m[str(k).strip().lower()] = str(v).strip()
                else:
                    m.pop(str(k).strip().lower(), None)
    except (ValueError, TypeError):
        pass
    return m


def _genres(c):
    return {r[1].strip().lower(): (r[0], r[1].strip())
            for r in c.execute("SELECT genre_id, genre FROM lutGenre WHERE genre <> ''")}


def _tag_genre(text_by_field):
    """(genre, field, keyword) from TAG_RULES, most specific field first."""
    for field in FIELD_ORDER:
        txt = text_by_field.get(field, '')
        if not txt:
            continue
        for genre, kws in TAG_RULES:
            for kw in kws:
                if re.search(r'(?<![a-z0-9])' + re.escape(kw) + r'(?![a-z0-9])', txt):
                    return genre, field, kw
    return None, None, None


def suggest(database, get, only_unset=True):
    """[{song_id, name, channel, scenes, current, suggested, reason,
    confidence, alt, alt_reason}] — confidence: 'scene' (trusted; alt carries any differing tag opinion),
    'tags' (no scene clue), 'conflict' (scenes of two genres), 'none'."""
    smap = scene_map(get)
    conn = sqlite3.connect(database)
    c = conn.cursor()
    try:
        genres = _genres(c)
        scenes = {}
        for sid, name in c.execute("SELECT ms.song_ID, s.sceneName FROM tblMusicScene ms "
                                   "JOIN tblScenes s ON s.scene_ID = ms.scene_ID"):
            scenes.setdefault(sid, []).append((name or '').strip())
        where = "WHERE COALESCE(m.genre, 0) = 0" if only_unset else ""
        rows = c.execute(
            f"SELECT m.song_id, COALESCE(m.displayName,''), COALESCE(m.song,''), COALESCE(m.genre,0), "
            f"COALESCE(d.title,''), COALESCE(d.uploader,''), COALESCE(d.description,''), d.raw_json "
            f"FROM tblMusic m LEFT JOIN tblMediaMetadata d ON d.media_type='music' AND d.media_id=m.song_id "
            f"{where} ORDER BY m.song_id").fetchall()
    finally:
        c.close()
        conn.close()
    out = []
    for sid, disp, fname, cur, title, chan, desc, raw in rows:
        try:
            j = json.loads(raw or '{}') if raw else {}
        except ValueError:
            j = {}
        # scene signal
        scene_genres = {}
        for sn in scenes.get(sid, []):
            key = sn.lower()
            g = smap.get(key) or (genres[key][1] if key in genres else None)
            if g:
                scene_genres.setdefault(g, []).append(sn)
        # tag signal
        text = {'tags': ' | '.join(str(t).lower() for t in (j.get('tags') or [])),
                'title': (title + ' ' + disp).lower(), 'channel': chan.lower(),
                'description': desc.lower()[:800]}
        tg, tf, tk = _tag_genre(text)
        rec = {'song_id': sid, 'name': disp or title or fname, 'channel': chan,
               'scenes': scenes.get(sid, []), 'current': cur,
               'suggested': None, 'reason': '', 'confidence': 'none',
               'alt': tg, 'alt_reason': f'{tf}: "{tk}"' if tg else ''}
        if len(scene_genres) == 1:
            # The scene decides. A differing tag opinion is shown alongside
            # (alt/alt_reason) but does NOT demote the row: "in the Rock
            # scene, tags mention pop" is normal for an 80s library, and
            # calling it a conflict would leave most of the library unlabeled.
            g, sns = next(iter(scene_genres.items()))
            rec.update(suggested=g, reason=f'in scene "{sns[0]}"', confidence='scene')
        elif len(scene_genres) > 1:
            rec.update(suggested=None, confidence='conflict',
                       reason='in scenes of different genres: ' +
                              ', '.join(f'{g} ({", ".join(s)})' for g, s in scene_genres.items()))
        elif tg:
            rec.update(suggested=tg, reason=rec['alt_reason'], confidence='tags')
        out.append(rec)
    return out


def apply(database, choices):
    """choices: [{song_id, genre}] — genre is a NAME (created in lutGenre if
    new, matched case-insensitively if not) or '' to skip. Returns
    {'updated': n, 'created': [names]}."""
    conn = sqlite3.connect(database)
    c = conn.cursor()
    created, updated = [], 0
    try:
        genres = _genres(c)
        for ch in choices:
            name = (ch.get('genre') or '').strip()
            try:
                sid = int(ch.get('song_id'))
            except (TypeError, ValueError):
                continue
            if not name:
                continue
            key = name.lower()
            if key not in genres:
                order = c.execute("SELECT COALESCE(MAX(orderBY), 0) + 1 FROM lutGenre").fetchone()[0]
                c.execute("INSERT INTO lutGenre(genre, directory, active, orderBY) VALUES (?, '', 1, ?)",
                          (name, order))
                genres[key] = (c.lastrowid, name)
                created.append(name)
            c.execute("UPDATE tblMusic SET genre = ? WHERE song_id = ?", (genres[key][0], sid))
            updated += c.rowcount
        conn.commit()
    finally:
        c.close()
        conn.close()
    return {'updated': updated, 'created': created}


def genre_names(database):
    conn = sqlite3.connect(database)
    try:
        return [r[0] for r in conn.execute("SELECT genre FROM lutGenre WHERE genre <> '' ORDER BY genre")]
    finally:
        conn.close()
