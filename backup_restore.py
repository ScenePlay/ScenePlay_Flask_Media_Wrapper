"""Backup / export / import for ScenePlay.

An archive is a small zip — database snapshot + uploaded images + manifest —
NOT the media files: every media row keeps its YouTube URL, so a restore
re-queues missing downloads through the normal yt-dlp pipeline instead of
hauling gigabytes around.

  archive layout:
    manifest.json     format version, app version, server name, timestamps
    ScenePlay.db      consistent snapshot (sqlite backup API, safe while live)
    uploads/...       static/uploads tree (portraits, map backgrounds, ...)

Two restore modes:
  * restore_replace  — whole-database swap (disaster recovery / migration).
    Takes a safety snapshot first, swaps the file atomically, rewrites media
    paths for THIS machine and re-queues missing files.
  * restore_merge    — dedup-aware import of campaigns / scenes / media links
    from the archive into the live database (sharing between servers).
    Media dedups by videoId, scenes/campaigns/genres match by name.
    HOMEBREW reference-library rows (custom feats, weapons, spells,
    subclasses + their features, monsters, ...) also merge, deduped by name —
    SRD rows never do (each box re-syncs those from the D&D API). LED
    patterns, characters/sessions/maps and server rows are hardware/box-
    specific and are NOT merged — use replace mode to move a whole box.

All DB work is plain sqlite3 against sql.database (same idiom as the queue
helpers), so tests can point it at a scratch file.
"""

import os
import json
import shutil
import sqlite3
import zipfile
from datetime import datetime
from pathlib import Path

import sql
from version import __version__

BACKUP_FORMAT = 1
_START_DIR = os.path.dirname(os.path.realpath(__file__))
BACKUP_DIR = os.path.join(_START_DIR, 'backups')
UPLOADS_DIR = os.path.join(_START_DIR, 'static', 'uploads')


def _now():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _stamp():
    return datetime.now().strftime('%Y%m%d-%H%M%S')


# ---------------------------------------------------------------------------
# Create / list / prune
# ---------------------------------------------------------------------------

def create_backup(label='manual'):
    """Build an archive in BACKUP_DIR and return its path.

    The DB snapshot uses sqlite's online backup API, so it is consistent even
    while the app and workers are writing."""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    safe_label = ''.join(ch if ch.isalnum() or ch in '-_' else '-' for ch in label)[:40] or 'manual'
    name = f'sceneplay-{safe_label}-{_stamp()}.zip'
    out_path = os.path.join(BACKUP_DIR, name)
    tmp_db = out_path + '.db.tmp'

    src = sqlite3.connect(sql.database)
    dst = sqlite3.connect(tmp_db)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()

    manifest = {
        'format': BACKUP_FORMAT,
        'app_version': __version__,
        'created_at': _now(),
        'label': label,
        'server_name': sql.appsettingGet('server_name', '') or '',
    }
    try:
        with zipfile.ZipFile(out_path, 'w', zipfile.ZIP_DEFLATED) as z:
            z.writestr('manifest.json', json.dumps(manifest, indent=2))
            z.write(tmp_db, 'ScenePlay.db')
            if os.path.isdir(UPLOADS_DIR):
                for root, _dirs, files in os.walk(UPLOADS_DIR):
                    for f in files:
                        full = os.path.join(root, f)
                        arc = os.path.join('uploads', os.path.relpath(full, UPLOADS_DIR))
                        z.write(full, arc)
    finally:
        os.remove(tmp_db)
    return out_path


def list_backups():
    """[{name, size, created}] newest first."""
    if not os.path.isdir(BACKUP_DIR):
        return []
    out = []
    for f in sorted(os.listdir(BACKUP_DIR), reverse=True):
        if not f.endswith('.zip'):
            continue
        p = os.path.join(BACKUP_DIR, f)
        st = os.stat(p)
        out.append({'name': f, 'size': st.st_size,
                    'created': datetime.fromtimestamp(st.st_mtime).strftime('%Y-%m-%d %H:%M')})
    return out


def prune_backups(keep=7):
    """Delete the oldest AUTOMATIC snapshots beyond `keep`. Manual and
    pre-restore archives are never pruned — only ones labeled 'auto'."""
    autos = sorted(f for f in os.listdir(BACKUP_DIR)
                   if f.startswith('sceneplay-auto-') and f.endswith('.zip')) if os.path.isdir(BACKUP_DIR) else []
    removed = 0
    for f in autos[:max(0, len(autos) - keep)]:
        os.remove(os.path.join(BACKUP_DIR, f))
        removed += 1
    return removed


# ---------------------------------------------------------------------------
# Archive validation / extraction
# ---------------------------------------------------------------------------

def _extract_db(zip_path, dest):
    """Pull ScenePlay.db out of the archive to `dest`, verify it's a sane
    ScenePlay database, and return the manifest dict. Raises ValueError."""
    with zipfile.ZipFile(zip_path) as z:
        names = set(z.namelist())
        if 'ScenePlay.db' not in names or 'manifest.json' not in names:
            raise ValueError('not a ScenePlay backup (missing ScenePlay.db / manifest.json)')
        manifest = json.loads(z.read('manifest.json'))
        if manifest.get('format', 0) > BACKUP_FORMAT:
            raise ValueError(f"backup format {manifest.get('format')} is newer than this server understands")
        with z.open('ScenePlay.db') as f, open(dest, 'wb') as out:
            shutil.copyfileobj(f, out)
    conn = sqlite3.connect(dest)
    try:
        ok = conn.execute('PRAGMA integrity_check').fetchone()[0]
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        conn.close()
    if ok != 'ok':
        raise ValueError('database in archive failed integrity check')
    if 'tblscenes' not in {t.lower() for t in tables}:
        raise ValueError('database in archive has no tblScenes — not ScenePlay data')
    return manifest


def _extract_uploads(zip_path, overwrite):
    """Restore uploads/ from the archive into static/uploads.
    ZipFile.extract-style path traversal is guarded by resolving each target."""
    count = 0
    base = Path(UPLOADS_DIR).resolve()
    with zipfile.ZipFile(zip_path) as z:
        for info in z.infolist():
            if not info.filename.startswith('uploads/') or info.is_dir():
                continue
            rel = info.filename[len('uploads/'):]
            target = (base / rel).resolve()
            if base not in target.parents and target != base:
                continue   # path traversal attempt — skip
            if target.exists() and not overwrite:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with z.open(info) as f, open(target, 'wb') as out:
                shutil.copyfileobj(f, out)
            count += 1
    return count


# ---------------------------------------------------------------------------
# Post-restore: point media rows at THIS machine and re-download what's missing
# ---------------------------------------------------------------------------

def _home():
    """Test seam: monkeypatched to a scratch dir in the test suite."""
    return str(Path.home())


def _local_media_index():
    """filename -> directory for every file under ~/Music and ~/Videos
    (recursive). Media filenames are videoId-based, so a name match IS the
    file — wherever it lives (moved library, second copy, subfolder)."""
    index = {}
    for root_dir in (os.path.join(_home(), 'Music'), os.path.join(_home(), 'Videos')):
        if not os.path.isdir(root_dir):
            continue
        for dirpath, _dirs, files in os.walk(root_dir):
            for f in files:
                index.setdefault(f, dirpath + os.sep)
    return index


def requeue_missing_media(only=None):
    """Point media rows at files that already exist on THIS machine, and queue
    downloads only for what is truly absent. Legacy rows (no urlSource) can't
    be re-downloaded and are left alone.

    Resolution order per row:
      1. the row's own path        (restoring on the same box/layout)
      2. the standard library path (~/Music/SP, ~/Videos/SP)
      3. filename search across ~/Music and ~/Videos — videoId filenames are
         unique, so the row is re-pointed at whichever folder has the file
      4. nothing found -> standard path + dnLoadStatus 1 (download queue)
    A found file also repairs a non-downloaded status (1/2/4 -> 3):
    re-downloading what's already on disk is the failure this prevents.

    only: optional {'music': {pks}, 'video': {pks}} to restrict the pass to
    specific rows — merge mode uses it so PRE-EXISTING local rows are never
    touched by a merge (that contract is pinned by tests).
    Returns {'requeued': n, 'found_local': m}."""
    music_path = os.path.join(_home(), 'Music', 'SP') + os.sep
    video_path = os.path.join(_home(), 'Videos', 'SP') + os.sep
    index = _local_media_index()
    conn = sqlite3.connect(sql.database)
    c = conn.cursor()
    requeued = found = 0
    for kind, tbl, pkcol, namecol, local in (
            ('music', 'tblMusic', 'song_id', 'song', music_path),
            ('video', 'tblVideoMedia', 'video_id', 'title', video_path)):
        rows = c.execute(
            f"SELECT {pkcol}, path, {namecol}, dnLoadStatus FROM {tbl} "
            f"WHERE urlSource IS NOT NULL AND urlSource <> ''").fetchall()
        for pk, path, name, status in rows:
            if only is not None and pk not in only.get(kind, ()):
                continue
            if not name:
                continue
            new_path = None
            if path and os.path.isfile(path + name):
                new_path = path
            elif os.path.isfile(local + name):
                new_path = local
            elif name in index:
                new_path = index[name]
            if new_path is not None:
                if new_path != path or status != 3:
                    c.execute(f"UPDATE {tbl} SET path = ?, dnLoadStatus = 3 WHERE {pkcol} = ?",
                              (new_path, pk))
                    found += 1
            else:
                # truly absent — standard path so the download lands right;
                # only downloaded rows flip to queued (failed rows keep their
                # status for the failed-retry flow)
                if status == 3:
                    c.execute(f"UPDATE {tbl} SET path = ?, dnLoadStatus = 1 WHERE {pkcol} = ?",
                              (local, pk))
                    requeued += 1
                elif path != local:
                    c.execute(f"UPDATE {tbl} SET path = ? WHERE {pkcol} = ?", (local, pk))
    conn.commit()
    c.close()
    conn.close()
    if requeued:
        sql.appsettingYT_QuePlayFlagUpdate(1)
    return {'requeued': requeued, 'found_local': found}


# ---------------------------------------------------------------------------
# Replace mode
# ---------------------------------------------------------------------------

def _upgrade_restored_db():
    """Bring a just-restored database up to the current schema — recreate any
    missing tables, then apply pending Alembic revisions — so restoring a
    backup taken on an OLDER app version works immediately. Needs the Flask
    app context the restore routes run in; returns False when unavailable
    (unit tests, CLI use) and leaves the upgrade to the next app start."""
    try:
        from flask import current_app
        from flask_migrate import upgrade as fm_upgrade
        from extensions import db
        if 'migrate' not in current_app.extensions:
            return False
        db.engine.dispose()      # pooled connections still point at the old file
        sql.sqlite_tune()        # restored file carries its own (old) journal mode
        sql.create_table()
        db.create_all()
        fm_upgrade()
        return True
    except Exception as e:
        print('post-restore schema upgrade skipped (next app start will retry):', e)
        return False


def restore_replace(zip_path, include_uploads=True):
    """Whole-database restore. Safety snapshot first; atomic file swap; WAL
    sidecars cleared; schema brought current; uploads overwritten; missing
    media re-queued.

    include_uploads=False restores the DATABASE ONLY: extracting a big
    uploads/ tree (battlemap images/videos) crashes low-memory boxes like a
    Pi Zero — images can be moved separately (rsync/USB into static/uploads)
    or simply left to the box they live on.

    The workers open a fresh sqlite connection per operation, so they pick up
    the new file immediately; the web app should still be restarted so its
    SQLAlchemy pool and appsetting-driven switches start clean."""
    tmp_db = os.path.join(BACKUP_DIR, f'.restore-{_stamp()}.db')
    os.makedirs(BACKUP_DIR, exist_ok=True)
    manifest = _extract_db(zip_path, tmp_db)

    safety = create_backup(label='pre-restore')

    os.replace(tmp_db, sql.database)
    for sidecar in ('-wal', '-shm'):
        try:
            os.remove(sql.database + sidecar)
        except OSError:
            pass
    upgraded = _upgrade_restored_db()
    uploads = _extract_uploads(zip_path, overwrite=True) if include_uploads else 0
    requeue = requeue_missing_media()
    return {
        'mode': 'replace',
        'from': manifest.get('server_name') or '?',
        'created_at': manifest.get('created_at'),
        'schema_upgraded': upgraded,
        'uploads_restored': uploads,
        'requeued_downloads': requeue['requeued'],
        'found_local': requeue['found_local'],
        'safety_backup': os.path.basename(safety),
    }


# ---------------------------------------------------------------------------
# Full-tree merge helpers (restore_merge(..., full=True))
# ---------------------------------------------------------------------------
# Identity & policy decisions (one-time box consolidation):
#   users        never copied; matched by lower(username), else fallback DM
#   characters   (owner, lower(name)) — LOCAL WINS, archive copy skipped;
#                sub-tables ride only with NEW characters, library ids
#                re-matched by item NAME (stats are denormalized, so a missing
#                library row degrades gracefully to a NULL lib id)
#   sessions     (campaign, lower(title), session_number); imported 'active'
#                status downgrades to 'planning' — a merge must never hijack
#                the live session
#   maps         (session, lower(name)); imported maps arrive is_active=0
#   tokens/fx    copied for NEW maps only — an existing map's live battle
#                state (positions, fog) is never touched
#   notes        (parent, title, body) dedup; sort_order appended past ceiling
#   lighting     copied only into scenes with NO local lighting of that type;
#                LED models matched by modelName (copied if missing), WLED
#                servers by serverName (copied if missing), effect/palette
#                catalog ids re-matched by name (kept verbatim on any miss)
#   excluded     dice rolls / roll log / token-position mirror / play counters
#                (logs, not world state) and user accounts / app settings


def _src_has(c, table):
    return bool(c.execute(
        "SELECT 1 FROM src.sqlite_master WHERE type='table' AND lower(name)=lower(?)",
        (table,)).fetchone())


def _common_cols(c, table, exclude=()):
    """Column-name intersection between src and live schemas (minus exclude) —
    lets archives from older/newer app versions merge cleanly."""
    src  = [r[1] for r in c.execute(f"PRAGMA src.table_info({table})")]
    live = [r[1] for r in c.execute(f"PRAGMA table_info({table})")]
    return [col for col in src if col in live and col not in exclude]


def _copy_row(c, table, data):
    cols = ', '.join(data)
    ph   = ', '.join('?' for _ in data)
    c.execute(f"INSERT INTO {table}({cols}) VALUES ({ph})", tuple(data.values()))
    return c.lastrowid


def _merge_full(c, genre_map, campaign_map, scene_map, media_map, fallback_user_id):
    """Merge the TTRPG tree + scene lighting from the attached src database.
    Runs inside restore_merge's transaction; every step guards on the src
    table existing so pre-ttrpg archives pass through untouched."""
    s = {'characters': 0, 'characters_skipped': 0, 'sessions': 0, 'maps': 0,
         'session_monsters': 0, 'party_links': 0, 'tokens': 0, 'map_effects': 0,
         'notes': 0, 'lighting': 0}

    # -- users: match only, never copy ---------------------------------------
    user_map = {}
    if _src_has(c, 'tblUsers'):
        for uid, uname in c.execute("SELECT user_id, username FROM src.tblUsers").fetchall():
            row = c.execute("SELECT user_id FROM tblUsers WHERE lower(username)=lower(?)",
                            (uname or '',)).fetchone()
            user_map[uid] = row[0] if row else fallback_user_id
    if fallback_user_id is None:
        row = (c.execute("SELECT user_id FROM tblUsers WHERE role='dm' AND active=1 "
                         "ORDER BY user_id LIMIT 1").fetchone()
               or c.execute("SELECT user_id FROM tblUsers ORDER BY user_id LIMIT 1").fetchone())
        fallback_user_id = row[0] if row else None

    # -- characters (+ sub-tables), local wins on (owner, name) --------------
    char_map = {}
    CHAR_SUBS = [
        ('tblCharacterWeapons',    'char_weapon_id', 'weapon_lib_id', 'weapon_name', 'tblWeaponsLibrary', 'weapon_lib_id'),
        ('tblCharacterArmor',      'char_armor_id',  'armor_lib_id',  'armor_name',  'tblArmorLibrary',   'armor_lib_id'),
        ('tblCharacterSpells',     'char_spell_id',  'spell_lib_id',  'spell_name',  'tblSpellsLibrary',  'spell_lib_id'),
        ('tblCharacterFeats',      'feat_id',      None, None, None, None),
        ('tblCharacterInventory',  'item_id',      None, None, None, None),
        ('tblCharacterSkills',     'skill_id',     None, None, None, None),
        ('tblCharacterResources',  'resource_id',  None, None, None, None),
        ('tblCharacterConditions', 'condition_id', None, None, None, None),
        ('tblCharacterNotes',      'note_id',      None, None, None, None),
    ]
    if _src_has(c, 'tblCharacters') and fallback_user_id is not None:
        cols = _common_cols(c, 'tblCharacters', exclude=('character_id',))
        for row in c.execute(f"SELECT character_id, {', '.join(cols)} FROM src.tblCharacters").fetchall():
            src_id, data = row[0], dict(zip(cols, row[1:]))
            data['user_id'] = user_map.get(data.get('user_id'), fallback_user_id)
            local = c.execute(
                "SELECT character_id FROM tblCharacters WHERE user_id=? AND lower(name)=lower(?)",
                (data['user_id'], data.get('name') or '')).fetchone()
            if local:
                char_map[src_id] = local[0]      # local wins; rewire refs to it
                s['characters_skipped'] += 1
                continue
            char_map[src_id] = _copy_row(c, 'tblCharacters', data)
            s['characters'] += 1
            for sub, pk, lib_col, name_col, lib_tbl, lib_pk in CHAR_SUBS:
                if not _src_has(c, sub):
                    continue
                sub_cols = _common_cols(c, sub, exclude=(pk,))
                for srow in c.execute(
                        f"SELECT {', '.join(sub_cols)} FROM src.{sub} WHERE character_id=?",
                        (src_id,)).fetchall():
                    sdata = dict(zip(sub_cols, srow))
                    sdata['character_id'] = char_map[src_id]
                    if lib_col and lib_col in sdata:
                        hit = c.execute(
                            f"SELECT {lib_pk} FROM {lib_tbl} WHERE lower(name)=lower(?)",
                            (sdata.get(name_col) or '',)).fetchone()
                        sdata[lib_col] = hit[0] if hit else None
                    _copy_row(c, sub, sdata)

    # -- monster templates: by name, copied when missing (SRD included, so
    #    session monsters always resolve) --------------------------------------
    template_map = {}
    if _src_has(c, 'tblMonsterTemplates'):
        tcols = _common_cols(c, 'tblMonsterTemplates', exclude=('template_id',))
        for row in c.execute(
                f"SELECT template_id, {', '.join(tcols)} FROM src.tblMonsterTemplates").fetchall():
            src_id, data = row[0], dict(zip(tcols, row[1:]))
            hit = c.execute("SELECT template_id FROM tblMonsterTemplates WHERE lower(name)=lower(?)",
                            (data.get('name') or '',)).fetchone()
            template_map[src_id] = hit[0] if hit else _copy_row(c, 'tblMonsterTemplates', data)

    # -- sessions ---------------------------------------------------------------
    session_map, new_sessions = {}, set()
    if _src_has(c, 'tblSessions'):
        scols = _common_cols(c, 'tblSessions', exclude=('session_id',))
        for row in c.execute(
                f"SELECT session_id, {', '.join(scols)} FROM src.tblSessions").fetchall():
            src_id, data = row[0], dict(zip(scols, row[1:]))
            if 'campaign_id' in data:
                data['campaign_id'] = campaign_map.get(data['campaign_id'])
            hit = c.execute(
                "SELECT session_id FROM tblSessions WHERE campaign_id IS ? "
                "AND lower(title)=lower(?) AND coalesce(session_number,1)=coalesce(?,1) "
                "ORDER BY session_id LIMIT 1",
                (data.get('campaign_id'), data.get('title') or '',
                 data.get('session_number'))).fetchone()
            if hit:
                session_map[src_id] = hit[0]
                continue
            if data.get('status') == 'active':
                data['status'] = 'planning'      # never hijack the live session
            session_map[src_id] = _copy_row(c, 'tblSessions', data)
            new_sessions.add(session_map[src_id])
            s['sessions'] += 1

    # -- party links -------------------------------------------------------------
    if _src_has(c, 'tblSessionParty') and session_map:
        pcols = _common_cols(c, 'tblSessionParty', exclude=('sp_id',))
        for row in c.execute(f"SELECT {', '.join(pcols)} FROM src.tblSessionParty").fetchall():
            data = dict(zip(pcols, row))
            sid = session_map.get(data.get('session_id'))
            cid = char_map.get(data.get('character_id'))
            if not sid or not cid:
                continue
            if c.execute("SELECT 1 FROM tblSessionParty WHERE session_id=? AND character_id=?",
                         (sid, cid)).fetchone():
                continue
            data.update(session_id=sid, character_id=cid)
            _copy_row(c, 'tblSessionParty', data)
            s['party_links'] += 1

    # -- session monsters: (session, display_name), local wins --------------------
    sm_map = {}
    if _src_has(c, 'tblSessionMonsters') and session_map:
        mcols = _common_cols(c, 'tblSessionMonsters', exclude=('monster_id',))
        for row in c.execute(
                f"SELECT monster_id, {', '.join(mcols)} FROM src.tblSessionMonsters").fetchall():
            src_id, data = row[0], dict(zip(mcols, row[1:]))
            sid = session_map.get(data.get('session_id'))
            if not sid:
                continue
            hit = c.execute(
                "SELECT monster_id FROM tblSessionMonsters WHERE session_id=? "
                "AND lower(display_name)=lower(?) LIMIT 1",
                (sid, data.get('display_name') or '')).fetchone()
            if hit:
                sm_map[src_id] = hit[0]
                continue
            data.update(session_id=sid,
                        template_id=template_map.get(data.get('template_id')))
            if data.get('template_id') is None:
                continue                          # template unresolvable — skip
            sm_map[src_id] = _copy_row(c, 'tblSessionMonsters', data)
            s['session_monsters'] += 1

    # -- battle maps ---------------------------------------------------------------
    map_map, new_maps = {}, set()
    if _src_has(c, 'tblBattleMaps') and session_map:
        bcols = _common_cols(c, 'tblBattleMaps', exclude=('map_id',))
        for row in c.execute(
                f"SELECT map_id, {', '.join(bcols)} FROM src.tblBattleMaps "
                "ORDER BY sort_order, map_id").fetchall():
            src_id, data = row[0], dict(zip(bcols, row[1:]))
            sid = session_map.get(data.get('session_id'))
            if not sid:
                continue
            hit = c.execute("SELECT map_id FROM tblBattleMaps WHERE session_id=? "
                            "AND lower(name)=lower(?) LIMIT 1",
                            (sid, data.get('name') or '')).fetchone()
            if hit:
                map_map[src_id] = hit[0]
                continue
            ceiling = c.execute("SELECT COALESCE(MAX(sort_order), 0) FROM tblBattleMaps "
                                "WHERE session_id=?", (sid,)).fetchone()[0]
            data.update(session_id=sid, is_active=0, sort_order=ceiling + 1)
            map_map[src_id] = _copy_row(c, 'tblBattleMaps', data)
            new_maps.add(map_map[src_id])
            s['maps'] += 1

        # tokens + effects ride only with NEW maps — an existing map's live
        # battle state (positions, fog) must never be disturbed by a merge
        if _src_has(c, 'tblBattleMapTokens'):
            kcols = _common_cols(c, 'tblBattleMapTokens', exclude=('token_id',))
            for row in c.execute(f"SELECT {', '.join(kcols)} FROM src.tblBattleMapTokens").fetchall():
                data = dict(zip(kcols, row))
                mid = map_map.get(data.get('map_id'))
                if not mid or mid not in new_maps:
                    continue
                ent_map = char_map if data.get('entity_type') == 'player' else sm_map
                ent = ent_map.get(data.get('entity_id'))
                if ent is None:
                    continue                      # entity didn't survive the merge
                data.update(map_id=mid, entity_id=ent)
                _copy_row(c, 'tblBattleMapTokens', data)
                s['tokens'] += 1
        if _src_has(c, 'tblBattleMapEffects'):
            ecols = _common_cols(c, 'tblBattleMapEffects', exclude=('effect_id',))
            for row in c.execute(f"SELECT {', '.join(ecols)} FROM src.tblBattleMapEffects").fetchall():
                data = dict(zip(ecols, row))
                mid = map_map.get(data.get('map_id'))
                if not mid or mid not in new_maps:
                    continue
                data['map_id'] = mid
                _copy_row(c, 'tblBattleMapEffects', data)
                s['map_effects'] += 1

    # -- notes (session + map): dedup by (parent, title, body) ---------------------
    for tbl, pk, parent_col, parent_map in (
            ('tblSessionNotes',  'note_id', 'session_id', session_map),
            ('tblBattleMapNotes', 'note_id', 'map_id',    map_map)):
        if not _src_has(c, tbl) or not parent_map:
            continue
        ncols = _common_cols(c, tbl, exclude=(pk,))
        for row in c.execute(
                f"SELECT {', '.join(ncols)} FROM src.{tbl} "
                f"ORDER BY {parent_col}, sort_order").fetchall():
            data = dict(zip(ncols, row))
            parent = parent_map.get(data.get(parent_col))
            if not parent:
                continue
            if c.execute(f"SELECT 1 FROM {tbl} WHERE {parent_col}=? AND title=? AND body=?",
                         (parent, data.get('title') or '', data.get('body') or '')).fetchone():
                continue
            ceiling = c.execute(
                f"SELECT COALESCE(MAX(sort_order), 0) FROM {tbl} WHERE {parent_col}=?",
                (parent,)).fetchone()[0]
            data.update({parent_col: parent, 'sort_order': ceiling + 1})
            _copy_row(c, tbl, data)
            s['notes'] += 1

    # -- scene lighting: only into scenes with NO local lighting of that type ------
    if _src_has(c, 'tblScenePattern'):
        model_map = {}
        if _src_has(c, 'tblLedTypeModel'):
            for mid, mname in c.execute(
                    "SELECT ledTypeModel_ID, modelName FROM src.tblLedTypeModel").fetchall():
                hit = c.execute("SELECT ledTypeModel_ID FROM tblLedTypeModel "
                                "WHERE lower(modelName)=lower(?)", (mname or '',)).fetchone()
                if hit:
                    model_map[mid] = hit[0]
                else:
                    mcols = _common_cols(c, 'tblLedTypeModel', exclude=('ledTypeModel_ID',))
                    row = c.execute(f"SELECT {', '.join(mcols)} FROM src.tblLedTypeModel "
                                    "WHERE ledTypeModel_ID=?", (mid,)).fetchone()
                    model_map[mid] = _copy_row(c, 'tblLedTypeModel', dict(zip(mcols, row)))
        pcols = _common_cols(c, 'tblScenePattern', exclude=('scenePattern_ID',))
        for row in c.execute(f"SELECT {', '.join(pcols)} FROM src.tblScenePattern").fetchall():
            data = dict(zip(pcols, row))
            scene = scene_map.get(data.get('scene_ID'))
            if not scene:
                continue
            if c.execute("SELECT 1 FROM tblScenePattern WHERE scene_ID=?", (scene,)).fetchone():
                continue                          # scene already has local LED lighting
            data['scene_ID'] = scene
            if 'ledTypeModel_ID' in data:
                data['ledTypeModel_ID'] = model_map.get(data['ledTypeModel_ID'],
                                                        data['ledTypeModel_ID'])
            _copy_row(c, 'tblScenePattern', data)
            s['lighting'] += 1

    if _src_has(c, 'tblWledPattern'):
        def _catalog_map(src_tbl, pk, name_col):
            out = {}
            if not _src_has(c, src_tbl):
                return out
            for cid, cname in c.execute(
                    f"SELECT {pk}, {name_col} FROM src.{src_tbl}").fetchall():
                hit = c.execute(f"SELECT {pk} FROM {src_tbl} WHERE lower({name_col})=lower(?)",
                                (cname or '',)).fetchone()
                if hit:
                    out[cid] = hit[0]
            return out
        effect_map  = _catalog_map('tblEffect',   'effect_ID',   'effectName')
        pallette_map = _catalog_map('tblPallette', 'pallette_ID', 'palletteName')
        server_map = {}
        if _src_has(c, 'tblServersIP'):
            for sid_, sname in c.execute(
                    "SELECT ServerIP_ID, serverName FROM src.tblServersIP").fetchall():
                hit = c.execute("SELECT ServerIP_ID FROM tblServersIP "
                                "WHERE lower(serverName)=lower(?)", (sname or '',)).fetchone()
                if hit:
                    server_map[sid_] = hit[0]
                else:
                    vcols = _common_cols(c, 'tblServersIP', exclude=('ServerIP_ID',))
                    row = c.execute(f"SELECT {', '.join(vcols)} FROM src.tblServersIP "
                                    "WHERE ServerIP_ID=?", (sid_,)).fetchone()
                    server_map[sid_] = _copy_row(c, 'tblServersIP', dict(zip(vcols, row)))
        wcols = _common_cols(c, 'tblWledPattern', exclude=('wledPattern_ID',))
        for row in c.execute(f"SELECT {', '.join(wcols)} FROM src.tblWledPattern").fetchall():
            data = dict(zip(wcols, row))
            scene = scene_map.get(data.get('scene_ID'))
            if not scene:
                continue
            if c.execute("SELECT 1 FROM tblWledPattern WHERE scene_ID=?", (scene,)).fetchone():
                continue                          # scene already has local WLED lighting
            data['scene_ID'] = scene
            if 'server_ID' in data:
                data['server_ID'] = server_map.get(data['server_ID'], data['server_ID'])
            if 'effect' in data:
                data['effect'] = effect_map.get(data['effect'], data['effect'])
            if 'pallette' in data:
                data['pallette'] = pallette_map.get(data['pallette'], data['pallette'])
            _copy_row(c, 'tblWledPattern', data)
            s['lighting'] += 1

    return s


# ---------------------------------------------------------------------------
# Merge mode
# ---------------------------------------------------------------------------

# Reference libraries whose HOMEBREW rows travel in a merge: (table, pk).
# Dedup is by lower(name) — tblFeaturesLibrary by (name, class, subclass,
# level) since the same feature name can exist across archetypes. SRD rows
# never merge: each box re-syncs those from the D&D API. Columns are copied
# by NAME INTERSECTION between the two schemas, so archives from older or
# newer versions merge cleanly.
HOMEBREW_LIBS = [
    ('tblFeatsLibrary',            'feat_lib_id'),
    ('tblWeaponsLibrary',          'weapon_lib_id'),
    ('tblArmorLibrary',            'armor_lib_id'),
    ('tblSpellsLibrary',           'spell_lib_id'),
    ('tblSkillsLibrary',           'skill_lib_id'),
    ('tblRacesLibrary',            'race_lib_id'),
    ('tblEquipmentLibrary',        'equipment_lib_id'),
    ('tblClassesLibrary',          'class_lib_id'),
    ('tblSubclassesLibrary',       'subclass_lib_id'),
    ('tblFeaturesLibrary',         'feature_lib_id'),
    ('tblMagicItemsLibrary',       'magic_item_lib_id'),
    ('tblConditionsLibrary',       'condition_lib_id'),
    ('tblTraitsLibrary',           'trait_lib_id'),
    ('tblWeaponPropertiesLibrary', 'weapon_prop_id'),
    ('tblRulesLibrary',            'rule_lib_id'),
    ('tblMonsterTemplates',        'template_id'),
]


def _merge_homebrew_libraries(c):
    """Copy source='homebrew' library rows from the attached src db, deduped
    by name. Tables absent on either side (older archive / older server) are
    skipped. Returns the number of rows copied."""
    copied = 0
    for tbl, pk in HOMEBREW_LIBS:
        if not c.execute("SELECT 1 FROM src.sqlite_master WHERE type='table' AND lower(name)=lower(?)",
                         (tbl,)).fetchone():
            continue
        if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND lower(name)=lower(?)",
                         (tbl,)).fetchone():
            continue
        src_cols  = [r[1] for r in c.execute(f"PRAGMA src.table_info({tbl})")]
        live_cols = [r[1] for r in c.execute(f"PRAGMA table_info({tbl})")]
        if 'source' not in src_cols or 'name' not in src_cols:
            continue
        cols = [col for col in src_cols if col in live_cols and col != pk]
        col_list = ', '.join(cols)
        rows = c.execute(f"SELECT {col_list} FROM src.{tbl} WHERE source = 'homebrew'").fetchall()
        for row in rows:
            data = dict(zip(cols, row))
            name = (data.get('name') or '').strip()
            if not name:
                continue
            if tbl == 'tblFeaturesLibrary':
                exists = c.execute(
                    "SELECT 1 FROM tblFeaturesLibrary WHERE lower(name)=lower(?) "
                    "AND lower(coalesce(class_name,''))=lower(?) "
                    "AND lower(coalesce(subclass_name,''))=lower(?) AND coalesce(level,0)=?",
                    (name, data.get('class_name') or '', data.get('subclass_name') or '',
                     data.get('level') or 0)).fetchone()
            else:
                exists = c.execute(f"SELECT 1 FROM {tbl} WHERE lower(name) = lower(?)",
                                   (name,)).fetchone()
            if exists:
                continue
            placeholders = ', '.join('?' for _ in cols)
            c.execute(f"INSERT INTO {tbl}({col_list}) VALUES ({placeholders})",
                      tuple(data[col] for col in cols))
            copied += 1
    return copied


def restore_merge(zip_path, include_uploads=True, full=False, fallback_user_id=None):
    """Dedup-aware import of the archive's campaigns, scenes, media and
    scene-links into the live database. Media rows match by videoId, genres/
    campaigns/scenes by name (case-insensitive); metadata rides along for new
    media rows. Legacy media rows without a videoId are skipped (no safe
    dedup identity). Returns a summary dict.

    full=True additionally merges the TTRPG tree (characters, sessions, maps,
    monsters, tokens, notes) and scene lighting — see _merge_full for the
    identity/conflict policy. fallback_user_id owns imported characters whose
    archive owner has no same-named account here (default: first active DM)."""
    tmp_db = os.path.join(BACKUP_DIR, f'.merge-{_stamp()}.db')
    os.makedirs(BACKUP_DIR, exist_ok=True)
    manifest = _extract_db(zip_path, tmp_db)

    music_path = os.path.join(_home(), 'Music', 'SP') + os.sep
    video_path = os.path.join(_home(), 'Videos', 'SP') + os.sep
    s = {'campaigns': 0, 'scenes': 0, 'music': 0, 'video': 0,
         'links': 0, 'skipped_legacy': 0, 'homebrew': 0, 'found_local': 0}

    conn = sqlite3.connect(sql.database)
    c = conn.cursor()
    try:
        c.execute("ATTACH DATABASE ? AS src", (tmp_db,))

        # genres by name
        genre_map = {}
        for gid, gname in c.execute("SELECT genre_id, genre FROM src.lutGenre").fetchall():
            row = c.execute("SELECT genre_id FROM lutGenre WHERE lower(genre) = lower(?)",
                            (gname or '',)).fetchone()
            if row is None and (gname or '').strip():
                c.execute("INSERT INTO lutGenre(genre, directory, active, orderBy) VALUES (?, '', 1, 0)",
                          (gname,))
                genre_map[gid] = c.lastrowid
            else:
                genre_map[gid] = row[0] if row else 0

        # media by videoId (metadata copied for NEW rows; downloads re-queued)
        src_has_meta = c.execute(
            "SELECT 1 FROM src.sqlite_master WHERE type='table' AND name='tblMediaMetadata'"
        ).fetchone()
        media_map = {'music': {}, 'video': {}}
        new_media = {'music': set(), 'video': set()}   # rows INSERTED by this merge
        for kind, tbl, pkcol, namecol, local in (
                ('music', 'tblMusic', 'song_id', 'song', music_path),
                ('video', 'tblVideoMedia', 'video_id', 'title', video_path)):
            # Archives from pre-videoId app versions lack the dedup columns
            # entirely — every row there is legacy, and SELECTing the missing
            # columns would abort the whole merge.
            src_cols = {r[1] for r in c.execute(f"PRAGMA src.table_info({tbl})")}
            if not {'videoId', 'displayName'} <= src_cols:
                s['skipped_legacy'] += c.execute(
                    f"SELECT COUNT(*) FROM src.{tbl}").fetchone()[0]
                continue
            rows = c.execute(
                f"SELECT {pkcol}, {namecol}, genre, urlSource, videoId, displayName "
                f"FROM src.{tbl}").fetchall()
            for pk, name, genre, urlSource, videoId, displayName in rows:
                if not videoId:
                    s['skipped_legacy'] += 1
                    continue
                row = c.execute(f"SELECT {pkcol} FROM {tbl} WHERE videoId = ?", (videoId,)).fetchone()
                if row:
                    media_map[kind][pk] = row[0]
                    continue
                c.execute(
                    f"INSERT INTO {tbl}(path, {namecol}, pTimes, playedDTTM, active, genre, que, "
                    f"urlSource, dnLoadStatus, videoId, displayName, metaStatus) "
                    f"VALUES (?, ?, 0, '', 1, ?, 0, ?, 1, ?, ?, 0)",
                    (local, name, genre_map.get(genre, 0), urlSource, videoId, displayName or ''))
                new_pk = c.lastrowid
                media_map[kind][pk] = new_pk
                new_media[kind].add(new_pk)
                s[kind] += 1
                meta = c.execute(
                    "SELECT title, duration, uploader, upload_date, thumbnail, view_count, "
                    "description, categories, raw_json, extracted_at "
                    "FROM src.tblMediaMetadata WHERE media_type = ? AND media_id = ?",
                    (kind, pk)).fetchone() if src_has_meta else None
                if meta:
                    c.execute(
                        "INSERT INTO tblMediaMetadata(media_type, media_id, title, duration, uploader, "
                        "upload_date, thumbnail, view_count, description, categories, raw_json, "
                        "retry_count, last_error, extracted_at, active) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, '', ?, 1)",
                        (kind, new_pk, *meta))
                    c.execute(f"UPDATE {tbl} SET metaStatus = 3 WHERE {pkcol} = ?", (new_pk,))
                else:
                    c.execute(f"UPDATE {tbl} SET metaStatus = 1 WHERE {pkcol} = ?", (new_pk,))

        # campaigns by name
        campaign_map = {}
        for cid, cname, active, order_by in c.execute(
                "SELECT campaign_id, campaign_name, active, order_by FROM src.tblCampaigns").fetchall():
            row = c.execute("SELECT campaign_id FROM tblCampaigns WHERE lower(campaign_name) = lower(?)",
                            (cname or '',)).fetchone()
            if row:
                campaign_map[cid] = row[0]
            else:
                c.execute("INSERT INTO tblCampaigns(campaign_name, active, order_by) VALUES (?, ?, ?)",
                          (cname, active, order_by))
                campaign_map[cid] = c.lastrowid
                s['campaigns'] += 1

        # scenes by (campaign, name) — name alone is not identity: two campaigns
        # can each have a "Tavern", and matching across campaigns merged the
        # archive's links into the wrong local scene. campaign_id IS ? is the
        # NULL-safe match (uncategorized scenes only pair with uncategorized).
        # ORDER BY makes the pick deterministic if local names are duplicated.
        scene_map = {}
        new_scenes = set()
        for sid, sname, active, order_by, camp in c.execute(
                "SELECT scene_ID, sceneName, active, orderBy, campaign_id FROM src.tblScenes").fetchall():
            tgt_camp = campaign_map.get(camp)
            row = c.execute(
                "SELECT scene_ID FROM tblScenes WHERE lower(sceneName) = lower(?) "
                "AND campaign_id IS ? ORDER BY scene_ID LIMIT 1",
                (sname or '', tgt_camp)).fetchone()
            if row:
                scene_map[sid] = row[0]
            else:
                c.execute("INSERT INTO tblScenes(sceneName, active, orderBy, campaign_id) VALUES (?, ?, ?, ?)",
                          (sname, active, order_by, tgt_camp))
                scene_map[sid] = c.lastrowid
                new_scenes.add(c.lastrowid)
                s['scenes'] += 1

        # scene-media links (skip duplicates; LED links are box-specific — not
        # merged). New scenes keep the archive's orderBy. Links landing in a
        # PRE-EXISTING scene are appended after its current orderBy ceiling —
        # source values would collide with local ones and interleave the
        # playlist. Source order is preserved by the ORDER BY on the reads.
        next_order = {}   # (link_table, tgt_scene) -> last orderBy handed out

        def link_order(tbl, tgt_scene, src_order):
            if tgt_scene in new_scenes:
                return src_order
            key = (tbl, tgt_scene)
            if key not in next_order:
                next_order[key] = c.execute(
                    f"SELECT COALESCE(MAX(orderBy), 0) FROM {tbl} WHERE scene_ID = ?",
                    (tgt_scene,)).fetchone()[0]
            next_order[key] += 1
            return next_order[key]

        # Backups from before tblMusicScene.loops existed lack the column —
        # select a literal 0 for those instead of failing the whole restore.
        _src_ms_cols = [r[1] for r in c.execute(
            "PRAGMA src.table_info('tblMusicScene')").fetchall()]
        _ms_loops = "loops" if 'loops' in _src_ms_cols else "0"
        for scene_src, song_src, order_by, volume, loops in c.execute(
                f"SELECT scene_ID, song_ID, orderBy, volume, {_ms_loops} FROM src.tblMusicScene "
                "ORDER BY scene_ID, orderBy").fetchall():
            tgt_scene = scene_map.get(scene_src)
            tgt_song = media_map['music'].get(song_src)
            if not tgt_scene or not tgt_song:
                continue
            if c.execute("SELECT 1 FROM tblMusicScene WHERE scene_ID = ? AND song_ID = ?",
                         (tgt_scene, tgt_song)).fetchone():
                continue
            c.execute("INSERT INTO tblMusicScene(scene_ID, song_ID, orderBy, volume, loops) VALUES (?, ?, ?, ?, ?)",
                      (tgt_scene, tgt_song, link_order('tblMusicScene', tgt_scene, order_by), volume, loops))
            s['links'] += 1
        for scene_src, video_src, screen, order_by, volume, loops in c.execute(
                "SELECT scene_ID, video_ID, DisplayScreen_ID, orderBy, volume, loops "
                "FROM src.tblVideoScene ORDER BY scene_ID, orderBy").fetchall():
            tgt_scene = scene_map.get(scene_src)
            tgt_video = media_map['video'].get(video_src)
            if not tgt_scene or not tgt_video:
                continue
            if c.execute("SELECT 1 FROM tblVideoScene WHERE scene_ID = ? AND video_ID = ?",
                         (tgt_scene, tgt_video)).fetchone():
                continue
            c.execute("INSERT INTO tblVideoScene(scene_ID, video_ID, DisplayScreen_ID, orderBy, volume, loops) "
                      "VALUES (?, ?, ?, ?, ?, ?)",
                      (tgt_scene, tgt_video, screen,
                       link_order('tblVideoScene', tgt_scene, order_by), volume, loops))
            s['links'] += 1

        # homebrew reference libraries (custom feats/weapons/spells/subclasses/
        # features/monsters...) — SRD rows stay behind, they re-sync per box
        s['homebrew'] = _merge_homebrew_libraries(c)

        # full-tree merge: characters/sessions/maps/notes + scene lighting.
        # Runs AFTER the libraries so template/lib name lookups see merged rows.
        if full:
            s.update(_merge_full(c, genre_map, campaign_map, scene_map,
                                 media_map, fallback_user_id))

        conn.commit()
        c.execute("DETACH DATABASE src")
    finally:
        c.close()
        conn.close()
        try:
            os.remove(tmp_db)
        except OSError:
            pass

    uploads = (_extract_uploads(zip_path, overwrite=False)  # never clobber local images
               if include_uploads else 0)
    if s['music'] or s['video']:
        # Files may already be on this box (consolidating boxes that shared a
        # media folder) — locate them first so only true gaps hit YouTube.
        # Scoped to the rows THIS merge inserted: pre-existing local rows are
        # never modified by a merge.
        s['found_local'] = requeue_missing_media(only=new_media)['found_local']
        sql.appsettingYT_QuePlayFlagUpdate(1)               # download the new rows
        sql.appsettingFlagUpdate('meta_que_switch', 1)      # fetch metadata where missing
    s.update({'mode': 'merge', 'from': manifest.get('server_name') or '?',
              'uploads_added': uploads})
    return s


# ---------------------------------------------------------------------------
# Nightly scheduler (started from app boot, same pattern as the queue workers)
# ---------------------------------------------------------------------------

POLL_SECONDS = 600          # scheduler granularity — checks 6x/hour
AUTO_INTERVAL_HOURS = 24


def backup_due():
    """True when auto-backup is on and the last one is older than a day."""
    if str(sql.appsettingGet('backup_auto', '0') or '0') != '1':
        return False
    last = sql.appsettingGet('backup_last', '') or ''
    if not last:
        return True
    try:
        age = datetime.now() - datetime.strptime(last, '%Y-%m-%d %H:%M:%S')
        return age.total_seconds() >= AUTO_INTERVAL_HOURS * 3600
    except ValueError:
        return True


def Backup_threader():
    import time
    while True:
        time.sleep(POLL_SECONDS)
        if os.getppid() == 1:      # parent died — don't linger as an orphan
            break
        try:
            if backup_due():
                create_backup(label='auto')
                sql.appsettingSet('backup_last', _now())
                keep = int(sql.appsettingGet('backup_keep', '7') or 7)
                prune_backups(keep)
        except Exception as e:     # one bad run must never kill the loop
            print('[backup] iteration error:', e)
