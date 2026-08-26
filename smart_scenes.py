"""Smart scenes: a scene whose members are DERIVED from media metadata.

A rule is a small JSON object stored per scene in tblSceneRules:

    {"media": ["music", "video"],          # which libraries to draw from
     "genres": ["Jazz"], "artists": ["Miles Davis"],
     "kinds": ["mix"], "decades": ["1980s"], "text": "coffee",
     "scenes": ["Jazz", "Classical"]}       # drawn from OTHER scenes' members

Every list is OR within itself and AND across fields; an empty field means
"any". "scenes" makes a scene a SOURCE for another: "everything in Jazz and
Classical that is a mix" needs no genre label at all — the scene you built
by hand is the taxonomy. A scene is never its own source. Members are matched against tblMusic / tblVideoMedia joined to
tblMediaMetadata (genre via lutGenre, artist / duration / release_year via
the facets in media_facets). refresh() ADDS matching media as scene links
with the library's usual defaults (volume 100, loops 0) and never removes a
link — what the DM added by hand stays. meta_que calls refresh_all() after
each extraction so new downloads land in the scenes they belong to.

Pure module (sqlite only). Scene rows are ordinary tblScenes rows; dropping
the rule turns a smart scene back into a plain one with its links intact.
"""
import json
import sqlite3

import media_facets

FIELDS = ('media', 'genres', 'artists', 'kinds', 'decades', 'text', 'scenes')
MEDIA = ('music', 'video')


def create_table(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS tblSceneRules (  rule_id INTEGER PRIMARY KEY AUTOINCREMENT,  "
                 "scene_ID INT UNIQUE,  rule_json TEXT,  auto_refresh INT DEFAULT 1,  "
                 "created_at TEXT,  last_refresh TEXT,  last_added INT DEFAULT 0)")


def normalize(rule):
    """Clean a rule dict from the UI/API: known fields only, lists of
    stripped strings, media limited to music/video (default both)."""
    r = rule or {}
    out = {}
    for f in FIELDS:
        v = r.get(f)
        if f == 'text':
            out[f] = (str(v or '')).strip()[:120]
        else:
            vals = v if isinstance(v, (list, tuple)) else ([v] if v else [])
            vals = [str(x).strip() for x in vals if str(x).strip()]
            if f == 'media':
                vals = [x for x in vals if x in MEDIA] or list(MEDIA)
            if f == 'kinds':
                vals = [x for x in vals if x in media_facets.KINDS]
            out[f] = sorted(set(vals), key=str.lower)
    return out


def describe(rule):
    """Human summary: 'Jazz · Miles Davis · mix · 1980s · "coffee" (music)'."""
    r = normalize(rule)
    bits = ([f'from {", ".join(r["scenes"])}'] if r['scenes'] else []) + r['genres'] + r['artists'] + \
        [media_facets.KINDS.get(k, k) for k in r['kinds']] + r['decades']
    if r['text']:
        bits.append(f'"{r["text"]}"')
    media = ' + '.join(r['media']) if r['media'] != list(MEDIA) else 'music + video'
    return (' · '.join(bits) or 'everything') + f' ({media})'


def facet_options(database):
    """What the builder can pick from, with counts."""
    conn = sqlite3.connect(database)
    try:
        genres = conn.execute(
            "SELECT g.genre, (SELECT COUNT(*) FROM tblMusic m WHERE m.genre=g.genre_id) + "
            "(SELECT COUNT(*) FROM tblVideoMedia v WHERE v.genre=g.genre_id) "
            "FROM lutGenre g WHERE g.genre <> '' ORDER BY g.genre").fetchall()
        artists = conn.execute(
            "SELECT artist, COUNT(*) FROM tblMediaMetadata WHERE COALESCE(artist,'') <> '' "
            "GROUP BY artist ORDER BY COUNT(*) DESC, artist").fetchall()
        durations = [r[0] for r in conn.execute("SELECT duration FROM tblMediaMetadata WHERE duration IS NOT NULL")]
        meta = conn.execute("SELECT raw_json, title FROM tblMediaMetadata").fetchall()
        scenes = conn.execute(
            "SELECT s.sceneName, (SELECT COUNT(*) FROM tblMusicScene ms WHERE ms.scene_ID = s.scene_ID) + "
            "(SELECT COUNT(*) FROM tblVideoScene vs WHERE vs.scene_ID = s.scene_ID) "
            "FROM tblScenes s WHERE s.scene_ID > 0 ORDER BY s.sceneName").fetchall()
    finally:
        conn.close()
    kinds = {}
    for d in durations:
        k = media_facets.media_kind(d)
        if k:
            kinds[k] = kinds.get(k, 0) + 1
    decades = {}
    for raw, title in meta:
        try:
            info = json.loads(raw or '{}') if raw else {}
        except ValueError:
            info = {}
        dec = media_facets.decade(info, title or '')
        if dec:
            decades[dec] = decades.get(dec, 0) + 1
    return {'scenes': [{'value': s, 'count': n} for s, n in scenes if n],
            'genres': [{'value': g, 'count': n} for g, n in genres],
            'artists': [{'value': a, 'count': n} for a, n in artists],
            'kinds': [{'value': k, 'label': media_facets.KINDS[k], 'count': kinds.get(k, 0)} for k in media_facets.KINDS],
            'decades': [{'value': d, 'count': n} for d, n in sorted(decades.items())]}


def match(database, rule, exclude_scene_id=None):
    """{'music': [(id, name)], 'video': [(id, name)]} for a rule.
    exclude_scene_id keeps a scene from being its own source."""
    r = normalize(rule)
    out = {'music': [], 'video': []}
    conn = sqlite3.connect(database)
    try:
        src = {'music': None, 'video': None}
        if r['scenes']:
            names = [s.lower() for s in r['scenes']]
            marks = ','.join('?' * len(names))
            sids = [row[0] for row in conn.execute(
                f"SELECT scene_ID FROM tblScenes WHERE lower(sceneName) IN ({marks})", names)
                if row[0] != exclude_scene_id]
            smarks = ','.join('?' * len(sids)) or 'NULL'
            src['music'] = {row[0] for row in conn.execute(f"SELECT song_ID FROM tblMusicScene WHERE scene_ID IN ({smarks})", sids)}
            src['video'] = {row[0] for row in conn.execute(f"SELECT video_ID FROM tblVideoScene WHERE scene_ID IN ({smarks})", sids)}
        for kind, tbl, pk, namecol in (('music', 'tblMusic', 'song_id', 'song'),
                                       ('video', 'tblVideoMedia', 'video_ID', 'title')):
            if kind not in r['media']:
                continue
            rows = conn.execute(
                f"SELECT m.{pk}, COALESCE(NULLIF(m.displayName,''), COALESCE(d.title, m.{namecol})), "
                f"COALESCE(g.genre,''), COALESCE(d.artist,''), d.duration, d.raw_json, COALESCE(d.title,''), "
                f"COALESCE(d.uploader,'') "
                f"FROM {tbl} m LEFT JOIN tblMediaMetadata d ON d.media_type=? AND d.media_id=m.{pk} "
                f"LEFT JOIN lutGenre g ON g.genre_id = m.genre "
                f"WHERE COALESCE(m.active,1) = 1 AND m.{namecol} IS NOT NULL AND m.{namecol} <> '' "
                f"ORDER BY 2", (kind,)).fetchall()
            gset = {x.lower() for x in r['genres']}
            aset = {x.lower() for x in r['artists']}
            txt = r['text'].lower()
            for rid, name, genre, artist, dur, raw, title, chan in rows:
                if src[kind] is not None and rid not in src[kind]:
                    continue
                if gset and genre.lower() not in gset:
                    continue
                if aset and artist.lower() not in aset:
                    continue
                if r['kinds'] and media_facets.media_kind(dur) not in r['kinds']:
                    continue
                if r['decades']:
                    try:
                        info = json.loads(raw or '{}') if raw else {}
                    except ValueError:
                        info = {}
                    if media_facets.decade(info, title) not in r['decades']:
                        continue
                if txt and txt not in f'{name} {title} {chan} {artist}'.lower():
                    continue
                out[kind].append((rid, name))
    finally:
        conn.close()
    return out


def _now():
    from datetime import datetime
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def create_scene(database, name, campaign_id, rule, auto_refresh=True):
    """Insert the scene (active, at the end of its campaign's order) with its
    rule, then fill it. Returns {'scene_id', 'added': {...}}."""
    name = (name or '').strip()[:80]
    if not name:
        raise ValueError('scene name required')
    conn = sqlite3.connect(database)
    try:
        create_table(conn)
        order = conn.execute("SELECT COALESCE(MAX(orderBy), 0) + 1 FROM tblScenes WHERE campaign_id = ?",
                             (campaign_id,)).fetchone()[0]
        cur = conn.execute("INSERT INTO tblScenes(sceneName, active, orderBy, campaign_id) VALUES (?, 1, ?, ?)",
                           (name, order, campaign_id))
        scene_id = cur.lastrowid
        conn.execute("INSERT INTO tblSceneRules(scene_ID, rule_json, auto_refresh, created_at) VALUES (?, ?, ?, ?)",
                     (scene_id, json.dumps(normalize(rule)), 1 if auto_refresh else 0, _now()))
        conn.commit()
    finally:
        conn.close()
    return {'scene_id': scene_id, 'added': refresh(database, scene_id)}


def set_rule(database, scene_id, rule, auto_refresh=True):
    """Attach / replace the rule on an EXISTING scene (makes it smart)."""
    conn = sqlite3.connect(database)
    try:
        create_table(conn)
        conn.execute("INSERT INTO tblSceneRules(scene_ID, rule_json, auto_refresh, created_at) VALUES (?, ?, ?, ?) "
                     "ON CONFLICT(scene_ID) DO UPDATE SET rule_json = excluded.rule_json, "
                     "auto_refresh = excluded.auto_refresh",
                     (int(scene_id), json.dumps(normalize(rule)), 1 if auto_refresh else 0, _now()))
        conn.commit()
    finally:
        conn.close()


def drop_rule(database, scene_id):
    """The scene stays, with every link it has; it just stops being smart."""
    conn = sqlite3.connect(database)
    try:
        create_table(conn)
        conn.execute("DELETE FROM tblSceneRules WHERE scene_ID = ?", (int(scene_id),))
        conn.commit()
    finally:
        conn.close()


def refresh(database, scene_id):
    """Add every matching medium not yet linked. Returns {'music': n, 'video': n}."""
    conn = sqlite3.connect(database)
    try:
        create_table(conn)
        row = conn.execute("SELECT rule_json FROM tblSceneRules WHERE scene_ID = ?", (int(scene_id),)).fetchone()
        if not row:
            return {'music': 0, 'video': 0}
        rule = json.loads(row[0] or '{}')
    finally:
        conn.close()
    matches = match(database, rule, exclude_scene_id=int(scene_id))
    added = {'music': 0, 'video': 0}
    conn = sqlite3.connect(database)
    try:
        have_m = {r[0] for r in conn.execute("SELECT song_ID FROM tblMusicScene WHERE scene_ID = ?", (scene_id,))}
        for rid, _ in matches['music']:
            if rid not in have_m:
                conn.execute("INSERT INTO tblMusicScene(scene_ID, song_ID, orderBy, volume, loops) VALUES (?, ?, 1, 100, 0)",
                             (scene_id, rid))
                added['music'] += 1
        have_v = {r[0] for r in conn.execute("SELECT video_ID FROM tblVideoScene WHERE scene_ID = ?", (scene_id,))}
        for rid, _ in matches['video']:
            if rid not in have_v:
                conn.execute("INSERT INTO tblVideoScene(scene_ID, video_ID, DisplayScreen_ID, orderBy, volume, loops) "
                             "VALUES (?, ?, 0, 1, 100, 0)", (scene_id, rid))
                added['video'] += 1
        conn.execute("UPDATE tblSceneRules SET last_refresh = ?, last_added = ? WHERE scene_ID = ?",
                     (_now(), added['music'] + added['video'], scene_id))
        conn.commit()
    finally:
        conn.close()
    return added


def refresh_all(database, auto_only=True):
    """Refresh every smart scene (only auto_refresh ones by default — the
    hook meta_que calls). Returns {scene_id: added}."""
    conn = sqlite3.connect(database)
    try:
        create_table(conn)
        ids = [r[0] for r in conn.execute(
            "SELECT scene_ID FROM tblSceneRules" + (" WHERE auto_refresh = 1" if auto_only else ""))]
    finally:
        conn.close()
    return {sid: refresh(database, sid) for sid in ids}


def list_rules(database):
    """Every smart scene with its rule, summary, member counts and campaign."""
    conn = sqlite3.connect(database)
    try:
        create_table(conn)
        rows = conn.execute(
            "SELECT r.scene_ID, s.sceneName, s.campaign_id, COALESCE(c.campaign_name,''), r.rule_json, "
            "r.auto_refresh, r.last_refresh, r.last_added, "
            "(SELECT COUNT(*) FROM tblMusicScene ms WHERE ms.scene_ID = r.scene_ID), "
            "(SELECT COUNT(*) FROM tblVideoScene vs WHERE vs.scene_ID = r.scene_ID) "
            "FROM tblSceneRules r JOIN tblScenes s ON s.scene_ID = r.scene_ID "
            "LEFT JOIN tblCampaigns c ON c.campaign_id = s.campaign_id ORDER BY s.sceneName").fetchall()
    finally:
        conn.close()
    out = []
    for sid, name, cid, cname, rj, auto, last, last_added, nm, nv in rows:
        rule = json.loads(rj or '{}')
        out.append({'scene_id': sid, 'name': name, 'campaign_id': cid, 'campaign': cname,
                    'rule': normalize(rule), 'summary': describe(rule), 'auto_refresh': bool(auto),
                    'last_refresh': last or '', 'last_added': last_added or 0, 'music': nm, 'video': nv})
    return out


def bulk_create(database, by, min_count, campaign_id, media=MEDIA, name_format='{value}',
                dry_run=False, attach_existing=False):
    """One smart scene per genre or artist with at least min_count matches.
    A name already present in that campaign is skipped — or, with
    attach_existing, that scene gets the rule instead (your hand-built
    "Rock" scene becomes the smart Rock scene). dry_run only reports.
    Returns [{name, count, action: created|attached|skipped, scene_id?}]."""
    if by not in ('genre', 'artist'):
        raise ValueError('by must be genre or artist')
    opts = facet_options(database)
    conn = sqlite3.connect(database)
    try:
        create_table(conn)
        existing = {r[1].strip().lower(): r[0] for r in conn.execute(
            "SELECT scene_ID, sceneName FROM tblScenes WHERE campaign_id = ?", (campaign_id,))}
        ruled = {r[0] for r in conn.execute("SELECT scene_ID FROM tblSceneRules")}
    finally:
        conn.close()
    out = []
    for opt in opts['genres' if by == 'genre' else 'artists']:
        rule = {'media': list(media), ('genres' if by == 'genre' else 'artists'): [opt['value']]}
        m = match(database, rule)
        n = len(m['music']) + len(m['video'])
        if n < min_count:
            continue
        name = name_format.format(value=opt['value'])
        key = name.strip().lower()
        if key in existing:
            sid = existing[key]
            if attach_existing and sid not in ruled:
                if not dry_run:
                    set_rule(database, sid, rule)
                    refresh(database, sid)
                out.append({'scene_id': sid, 'name': name, 'count': n, 'action': 'attached'})
            else:
                out.append({'scene_id': sid, 'name': name, 'count': n, 'action': 'skipped'})
            continue
        if dry_run:
            out.append({'name': name, 'count': n, 'action': 'created'})
        else:
            res = create_scene(database, name, campaign_id, rule)
            out.append({'scene_id': res['scene_id'], 'name': name, 'count': n, 'action': 'created'})
        existing[key] = -1
    return out
