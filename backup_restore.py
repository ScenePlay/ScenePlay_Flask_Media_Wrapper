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

def requeue_missing_media():
    """Rewrite media paths to this machine's convention and queue downloads
    for id-based rows whose file is absent. Legacy rows (no urlSource) can't
    be re-downloaded and are left alone. Returns {'requeued': n}."""
    music_path = str(Path.home()) + '/Music/SP/'
    video_path = str(Path.home()) + '/Videos/SP/'
    conn = sqlite3.connect(sql.database)
    c = conn.cursor()
    requeued = 0
    for tbl, pkcol, namecol, local in (('tblMusic', 'song_id', 'song', music_path),
                                       ('tblVideoMedia', 'video_id', 'title', video_path)):
        c.execute(f"UPDATE {tbl} SET path = ? WHERE urlSource IS NOT NULL AND urlSource <> ''", (local,))
        c.execute(f"SELECT {pkcol}, path || {namecol} FROM {tbl} "
                  f"WHERE urlSource IS NOT NULL AND urlSource <> '' AND dnLoadStatus = 3")
        for pk, full in c.fetchall():
            if full and not os.path.exists(full):
                c.execute(f"UPDATE {tbl} SET dnLoadStatus = 1 WHERE {pkcol} = ?", (pk,))
                requeued += 1
    conn.commit()
    c.close()
    conn.close()
    if requeued:
        sql.appsettingYT_QuePlayFlagUpdate(1)
    return {'requeued': requeued}


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
        'safety_backup': os.path.basename(safety),
    }


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


def restore_merge(zip_path, include_uploads=True):
    """Dedup-aware import of the archive's campaigns, scenes, media and
    scene-links into the live database. Media rows match by videoId, genres/
    campaigns/scenes by name (case-insensitive); metadata rides along for new
    media rows. Legacy media rows without a videoId are skipped (no safe
    dedup identity). Returns a summary dict."""
    tmp_db = os.path.join(BACKUP_DIR, f'.merge-{_stamp()}.db')
    os.makedirs(BACKUP_DIR, exist_ok=True)
    manifest = _extract_db(zip_path, tmp_db)

    music_path = str(Path.home()) + '/Music/SP/'
    video_path = str(Path.home()) + '/Videos/SP/'
    s = {'campaigns': 0, 'scenes': 0, 'music': 0, 'video': 0,
         'links': 0, 'skipped_legacy': 0, 'homebrew': 0}

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
