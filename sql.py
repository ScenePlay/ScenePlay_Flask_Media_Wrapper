import sqlite3
import subprocess
import os
from glob import glob
import time
from datetime import datetime, timedelta
from pathlib import Path
import logging
import unicodedata
from unittest import case
from extensions import *
from collections import defaultdict
import mpv_ipc

#logging.basicConfig(filename='myapp.log', level=logging.DEBUG, format='%(asctime)s %(levelname)s %(name)s %(message)s')
#logger=logging.getLogger(__name__)

database = databaseDir


def sqlite_tune():
    """Put the database in WAL journal mode (idempotent; the mode persists in
    the file itself). In the default delete-journal mode every commit takes an
    exclusive lock and costs several fsyncs — on this project's typical
    storage (SD cards, NTFS/FUSE mounts) that serialized every reader behind
    every writer, and with six polling workers it escalated into lock storms:
    'database is locked' errors and a stalled relay receiver. In WAL, readers
    never block and a commit is a single append. Called at app startup and
    after a replace-restore (a restored backup carries its own old mode)."""
    conn = sqlite3.connect(database, timeout=30)
    try:
        conn.execute('PRAGMA journal_mode=WAL')
        # Fold the WAL into the main file and truncate it. In WAL mode recent
        # writes live in ScenePlay.db-wal, so a bare file copy of ScenePlay.db
        # (USB/scp between boxes) silently loses the tail — this makes the
        # main file complete as of every app start. (The ONLY fully-safe way
        # to move a live database remains the app's Backup feature, which
        # snapshots via sqlite's backup API.)
        conn.execute('PRAGMA wal_checkpoint(TRUNCATE)')
    finally:
        conn.close()


def create_table():
    conn = sqlite3.connect(database)
    conn.text_factory = lambda x: unicodedata(x, 'utf-8', 'ignore')
    c = conn.cursor()
    # WAL so readers and the writer don't block each other (many threads share
    # this file: web requests, relay receiver, download/metadata workers).
    # Persists in the db file; a no-op when already set. The current live DB
    # is already WAL — this codifies it for fresh installs.
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA synchronous=NORMAL")
    # c.execute("drop table tblscenes")
    c.execute("CREATE TABLE IF NOT EXISTS tblUsers ( user_id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL, display_name TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'player', active INT NOT NULL DEFAULT 1, created_at TEXT NOT NULL)")
    c.execute("CREATE TABLE IF NOT EXISTS tblCharacters ( character_id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INT NOT NULL, name TEXT NOT NULL, char_class TEXT DEFAULT '', race TEXT DEFAULT '', level INT DEFAULT 1, background TEXT DEFAULT '', portrait_path TEXT DEFAULT '', hp_current INT DEFAULT 0, hp_max INT DEFAULT 0, ac INT DEFAULT 10, str_val INT DEFAULT 10, dex_val INT DEFAULT 10, con_val INT DEFAULT 10, int_val INT DEFAULT 10, wis_val INT DEFAULT 10, cha_val INT DEFAULT 10, speed INT DEFAULT 30, initiative_bonus INT DEFAULT 0, passive_perception INT DEFAULT 10, gold INT DEFAULT 0, silver INT DEFAULT 0, copper INT DEFAULT 0, active INT DEFAULT 1, created_at TEXT NOT NULL)")
    c.execute("CREATE TABLE IF NOT EXISTS tblCharacterResources ( resource_id INTEGER PRIMARY KEY AUTOINCREMENT, character_id INT NOT NULL, resource_name TEXT NOT NULL, current_val INT DEFAULT 0, max_val INT DEFAULT 0, order_by INT DEFAULT 0)")
    c.execute("CREATE TABLE IF NOT EXISTS tblCharacterConditions ( condition_id INTEGER PRIMARY KEY AUTOINCREMENT, character_id INT NOT NULL, condition_name TEXT NOT NULL, notes TEXT DEFAULT '', created_at TEXT NOT NULL)")
    c.execute("CREATE TABLE IF NOT EXISTS tblCharacterInventory ( item_id INTEGER PRIMARY KEY AUTOINCREMENT, character_id INT NOT NULL, item_name TEXT NOT NULL, quantity INT DEFAULT 1, weight TEXT DEFAULT '', notes TEXT DEFAULT '', equipped INT DEFAULT 0, order_by INT DEFAULT 0)")
    c.execute("CREATE TABLE IF NOT EXISTS tblCharacterSkills ( skill_id INTEGER PRIMARY KEY AUTOINCREMENT, character_id INT NOT NULL, skill_name TEXT NOT NULL, bonus INT DEFAULT 0, proficient INT DEFAULT 0, order_by INT DEFAULT 0)")
    c.execute("CREATE TABLE IF NOT EXISTS tblCharacterNotes ( note_id INTEGER PRIMARY KEY AUTOINCREMENT, character_id INT NOT NULL, note_text TEXT NOT NULL, created_at TEXT NOT NULL)")
    c.execute("CREATE TABLE IF NOT EXISTS tblSessions ( session_id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, session_number INT DEFAULT 1, campaign_id INT, status TEXT DEFAULT 'planning', dm_notes TEXT DEFAULT '', session_date TEXT DEFAULT '', created_at TEXT NOT NULL)")
    c.execute("CREATE TABLE IF NOT EXISTS tblSessionParty ( sp_id INTEGER PRIMARY KEY AUTOINCREMENT, session_id INT NOT NULL, character_id INT NOT NULL, is_active INT DEFAULT 1, joined_at TEXT NOT NULL)")
    c.execute("CREATE TABLE IF NOT EXISTS tblMonsterTemplates ( template_id INTEGER PRIMARY KEY AUTOINCREMENT, api_index TEXT UNIQUE, name TEXT NOT NULL, cr TEXT DEFAULT '0', monster_type TEXT DEFAULT '', size TEXT DEFAULT '', hp_max INT DEFAULT 0, ac INT DEFAULT 10, source TEXT DEFAULT 'srd', stats_json TEXT DEFAULT '{}', created_at TEXT NOT NULL)")
    c.execute("CREATE TABLE IF NOT EXISTS tblSessionMonsters ( monster_id INTEGER PRIMARY KEY AUTOINCREMENT, session_id INT NOT NULL, template_id INT NOT NULL, display_name TEXT NOT NULL, hp_current INT DEFAULT 0, hp_max INT DEFAULT 0, ac INT DEFAULT 10, initiative INT DEFAULT 0, conditions TEXT DEFAULT '[]', is_alive INT DEFAULT 1, sort_order INT DEFAULT 0)")
    c.execute("CREATE TABLE IF NOT EXISTS lutGenre (  genre_id INTEGER PRIMARY KEY AUTOINCREMENT,  genre TEXT,  directory TEXT,  active INT,  orderBY INT)")
    c.execute("CREATE TABLE IF NOT EXISTS tblAppSettings (  ID INTEGER PRIMARY KEY AUTOINCREMENT,  name TEXT,  value TEXT,  typevalue TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS tblCampaigns  (  campaign_id INTEGER NOT NULL PRIMARY KEY,  campaign_name TEXT,  active INT,  order_by TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS tblGlobalVar (  globalVar_id INTEGER PRIMARY KEY AUTOINCREMENT,  varName TEXT,  varType TEXT,  varValue TEXT,  active INT)")
    c.execute("CREATE TABLE IF NOT EXISTS tblHours (  hours_id INTEGER PRIMARY KEY AUTOINCREMENT,  startDTTM TEXT,  endDTTM TEXT,  startTime TEXT,  endTime TEXT,  gmt INT,  active INT)")
    c.execute("CREATE TABLE IF NOT EXISTS tblLED (  led_ID INTEGER PRIMARY KEY AUTOINCREMENT,  ledJSON TEXT,  active INT)")
    c.execute("CREATE TABLE IF NOT EXISTS tblLEDConfig (  ledConfig_ID INTEGER PRIMARY KEY AUTOINCREMENT,  pin INT,  ledCount INT, brightness Real,  active INT)")
    c.execute("CREATE TABLE IF NOT EXISTS tblLEDTypeModel (  ledTypeModel_ID INTEGER PRIMARY KEY AUTOINCREMENT,  modelName TEXT,  ledJSON TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS tblMusic (  song_id INTEGER PRIMARY KEY AUTOINCREMENT,  path TEXT,  song TEXT,  pTimes INT,  playedDTTM TEXT,  active INT,  genre INT,  que INT,  urlSource TEXT,  dnLoadStatus INT,  videoId TEXT,  displayName TEXT,  metaStatus INT DEFAULT 0,  metaNextRetry TEXT,  dnLastError TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS tblMusicScene (  musicScene_ID INTEGER PRIMARY KEY AUTOINCREMENT,  scene_ID INT,  song_ID INT,  orderBy INT,  volume INT, loops INT)")
    c.execute("CREATE TABLE IF NOT EXISTS tblScenePattern (  scenePattern_ID INTEGER PRIMARY KEY AUTOINCREMENT,  scene_ID INT,  ledTypeModel_ID INT,  color TEXT,  wait_ms INT,  iterations INT,  direction INT, cdiff TEXT, orderBy INT, outPin INT, brightness Real)")
    c.execute("CREATE TABLE IF NOT EXISTS tblScenes (  scene_ID INTEGER PRIMARY KEY AUTOINCREMENT,  sceneName TEXT,  active INT,  orderBy INT,  campaign_id INT)")
    c.execute("CREATE TABLE IF NOT EXISTS tblServerRole (  ID INTEGER PRIMARY KEY AUTOINCREMENT,  name TEXT,  active INT,  orderBy INT)")
    c.execute("CREATE TABLE IF NOT EXISTS tblServersIP (  ServerIP_ID INTEGER PRIMARY KEY AUTOINCREMENT,  serverName TEXT,  version TEXT,  ipAddress TEXT,  ports TEXT,  active INT,  PingTime TEXT,  serverroleid INT)")
    c.execute("CREATE TABLE IF NOT EXISTS tblVideoMedia (  video_ID INTEGER PRIMARY KEY AUTOINCREMENT,  path TEXT,  title TEXT,  pTimes INT,  playedDTTM TEXT,  active INT,  genre INT,  que INT,  urlSource TEXT,  dnLoadStatus INT,  videoId TEXT,  displayName TEXT,  metaStatus INT DEFAULT 0,  metaNextRetry TEXT,  dnLastError TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS tblVideoScene (  videoScene_ID INTEGER PRIMARY KEY AUTOINCREMENT,  scene_ID INT,  video_ID INT,  DisplayScreen_ID INT,  orderBy INT,  volume INT, loops INT)")
    c.execute("CREATE TABLE IF NOT EXISTS tblwledPattern (  wledPattern_ID INTEGER PRIMARY KEY AUTOINCREMENT,  scene_ID INT, server_ID INT,  effect INT,  pallette INT,  color1 TEXT,  color2 TEXT,  color3 TEXT,  speed INT,  brightness INT,  orderBy INT)")
    c.execute("CREATE TABLE IF NOT EXISTS tbleffect (  effect_ID INTEGER PRIMARY KEY AUTOINCREMENT,  effectName TEXT, ef_ID INT)")
    c.execute("CREATE TABLE IF NOT EXISTS tblpallette (  pallette_ID INTEGER PRIMARY KEY AUTOINCREMENT,  palletteName TEXT, pa_ID INT)")
    c.execute("CREATE TABLE IF NOT EXISTS lutStatus (pkey INTEGER PRIMARY KEY AUTOINCREMENT,  status_ID INT,  status TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS tblCronSchedule (  schedule_id INTEGER PRIMARY KEY AUTOINCREMENT,  name TEXT,  minute TEXT,  hour TEXT,  day_of_month TEXT,  month TEXT,  day_of_week TEXT,  command TEXT,  description TEXT,  active INT)")
    # yt-dlp metadata per media row (media_type 'music'|'video' + media_id soft-FK to
    # tblMusic.song_id / tblVideoMedia.video_ID). Raw JSON kept alongside promoted columns.
    c.execute("CREATE TABLE IF NOT EXISTS tblMediaMetadata (  metadata_id INTEGER PRIMARY KEY AUTOINCREMENT,  media_type TEXT,  media_id INT,  title TEXT,  duration INT,  uploader TEXT,  upload_date TEXT,  thumbnail TEXT,  view_count INT,  description TEXT,  categories TEXT,  raw_json TEXT,  retry_count INT DEFAULT 0,  last_error TEXT,  extracted_at TEXT,  active INT DEFAULT 1)")
    # Playlist-expansion jobs: a playlist URL is queued here and a background worker
    # expands it into single-video intakes. status uses the lutStatus lexicon (1-4).
    c.execute("CREATE TABLE IF NOT EXISTS tblPlaylistQueue (  playlist_id INTEGER PRIMARY KEY AUTOINCREMENT,  url TEXT,  media_type TEXT,  scene_ID INT,  status INT DEFAULT 1,  retry_count INT DEFAULT 0,  last_error TEXT,  created_at TEXT,  next_retry TEXT)")
    # Dedup identity: one media row per YouTube video per table. Partial indexes so
    # legacy rows (videoId NULL) stay legal; SQLite treats NULLs as distinct anyway,
    # but the WHERE clause makes the intent explicit. try/except: on a legacy DB that
    # hasn't run app.py's ALTER migrations yet the column doesn't exist — app boot
    # always runs the ALTERs before this, so the index lands on first boot.
    try:
        c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_tblMusic_videoId ON tblMusic(videoId) WHERE videoId IS NOT NULL")
        c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_tblVideoMedia_videoId ON tblVideoMedia(videoId) WHERE videoId IS NOT NULL")
    except sqlite3.OperationalError:
        pass
    conn.commit()
    c.close()




def getLEDOutPIN():
    conn = sqlite3.connect(database)
    c = conn.cursor()
    c.execute("SELECT * FROM tblLEDConfig where active = 1")    
    data = c.fetchall()
    conn.commit()
    c.close()
    conn.close()
    return data

def appsettings(apparray):
    names = [a[0] for a in apparray]
    conn = sqlite3.connect(database)
    c = conn.cursor()
    placeholders = ','.join('?' for _ in names)
    c.execute(f"DELETE FROM tblAppSettings WHERE name IN ({placeholders})", names)
    conn.commit()
    c.close()
    conn.close()
    for a in apparray:
        CRUD_tblAppSettings(a,"C")
    pass

def appsettingYT_QuePlayFlagUpdatePID(val):
    conn = sqlite3.connect(database)
    c = conn.cursor()
    c.execute("Update tblAppSettings set value = ?  where name =  'yt_que_PID'",(val,))    
    conn.commit()
    c.close()
    conn.close()

def appsettingYT_QuePlayFlagUpdate(val):
    conn = sqlite3.connect(database)
    c = conn.cursor()
    c.execute("Update tblAppSettings set value = ?  where name =  'yt_que_switch'",(val,))    
    conn.commit()
    c.close()
    conn.close()
    
def appsettingYT_QueFlag():
    conn = sqlite3.connect(database)
    c = conn.cursor()
    c.execute("SELECT * FROM tblAppSettings where name =  'yt_que_switch'")    
    data = c.fetchall()
    conn.commit()
    c.close()
    conn.close()
    return data

def select_YT_Que_Next():
    conn = sqlite3.connect(database)
    c = conn.cursor()
    c.execute("Select * from ( \
                                Select song_id as pkey,path, song as title, urlSource,substr(song,INSTR(song,'.')+1,LENGTH(song)) as media , 'tblMusic' as tbl \
                                    from tblMusic where urlSource not null and dnLoadStatus=1 \
                             union \
                                Select video_ID as pkey, path, title, urlSource,substr( title , INSTR(title,'.')+1 , LENGTH(title)) as media , 'tblVideoMedia' as tbl \
                                    from tblVideoMedia where urlSource not null and dnLoadStatus=1 \
                             ) Order By RANDOM(), pkey ASC LIMIT 1;")

    data = c.fetchall()
    conn.commit()
    c.close()
    conn.close()
    return data


# ---------------------------------------------------------------------------
# Metadata queue / video-id dedup helpers
# ---------------------------------------------------------------------------

def appsettingFlagUpdate(name, val):
    """Generic switch setter for the new worker flags (meta_que_switch /
    playlist_que_switch) — same row-update the bespoke yt_que helpers do."""
    conn = sqlite3.connect(database)
    c = conn.cursor()
    c.execute("Update tblAppSettings set value = ?  where name = ?", (val, name))
    conn.commit()
    c.close()
    conn.close()


def appsettingFlagGet(name):
    conn = sqlite3.connect(database)
    c = conn.cursor()
    c.execute("SELECT value FROM tblAppSettings where name = ?", (name,))
    row = c.fetchone()
    c.close()
    conn.close()
    return row[0] if row else None


def _media_cols(media_type):
    """(table, pk column, name column) for 'music' | 'video'."""
    if media_type == 'music':
        return 'tblMusic', 'song_id', 'song'
    return 'tblVideoMedia', 'video_ID', 'title'


def get_media_by_videoid(media_type, videoId):
    """Return (pk, dnLoadStatus, metaStatus) for the row holding this YouTube id,
    or None. This is the dedup lookup."""
    tbl, pk, _ = _media_cols(media_type)
    conn = sqlite3.connect(database)
    c = conn.cursor()
    c.execute(f"SELECT {pk}, dnLoadStatus, metaStatus FROM {tbl} WHERE videoId = ?", (videoId,))
    row = c.fetchone()
    c.close()
    conn.close()
    return row


def insert_media_dedup(media_type, path, filename, url, videoId, displayName):
    """Insert a media row keyed by videoId, safely under concurrency.

    Returns (pk, created). The partial UNIQUE index on videoId turns a lost
    SELECT-then-INSERT race into an IntegrityError here, and we re-SELECT the
    winning row — so two simultaneous enqueues of the same video (form intake,
    playlist worker, Chrome extension) always converge on ONE row."""
    tbl, pk, namecol = _media_cols(media_type)
    conn = sqlite3.connect(database)
    c = conn.cursor()
    try:
        c.execute(f"INSERT INTO {tbl}(path, {namecol}, pTimes, playedDTTM, active, genre, que, urlSource, dnLoadStatus, videoId, displayName, metaStatus) "
                  "VALUES (?, ?, 0, '', 1, 0, 0, ?, 1, ?, ?, 1)",
                  (path, filename, url, videoId, displayName))
        conn.commit()
        return c.lastrowid, True
    except sqlite3.IntegrityError:
        conn.rollback()
        c.execute(f"SELECT {pk} FROM {tbl} WHERE videoId = ?", (videoId,))
        row = c.fetchone()
        return (row[0] if row else None), False
    finally:
        c.close()
        conn.close()


def enqueue_single(url, mediaType, scene_ID, flname=''):
    """Intake ONE video: extract its id, dedup by videoId, add a scene-link, and
    enqueue download + metadata. Shared by the form intake, the Chrome-extension
    route and the playlist worker (so all three dedup identically). Returns
    (pk, created, reason). reason is '' on success or an error string.

    - filename on disk is <videoId>.<ext> (metadata later fills the human name);
    - a typed flname seeds displayName as an override metadata won't overwrite;
    - on a dedup hit whose download failed (but is not permanently unavailable),
      the shared row is re-queued so every scene benefits."""
    from ytid import youtube_video_id, canonical_watch_url
    media_type = 'music' if mediaType == 'mp3' else 'video'
    try:
        scene_ID = int(scene_ID) if str(scene_ID) != '' else 0
    except (TypeError, ValueError):
        scene_ID = 0

    vid = youtube_video_id(url)
    if not vid:
        # No parseable id: only proceed if the caller supplied a name (legacy path).
        if not flname:
            return None, False, 'no video id and no name'
        return _enqueue_legacy(url, mediaType, scene_ID, flname), True, ''

    path = (str(Path.home()) + "/Music/SP/") if media_type == 'music' else (str(Path.home()) + "/Videos/SP/")
    filename = f"{vid}.{mediaType}"
    canonical = canonical_watch_url(vid)

    existing = get_media_by_videoid(media_type, vid)
    if existing:
        pk, dn_status, meta_status = existing
        created = False
        # Re-queue a failed shared file (unless permanently unavailable, status 5).
        if dn_status == 4 and meta_status != 5:
            _set_dnload_status(media_type, pk, 1)
            appsettingYT_QuePlayFlagUpdate(1)
        # Re-adding a known video is also the natural "try again" for metadata
        # that never landed (0) or failed out of retries (4) — self-guarded.
        requeue_metadata_if_missing(media_type, pk)
    else:
        pk, created = insert_media_dedup(media_type, path, filename, canonical, vid, flname or '')
        appsettingYT_QuePlayFlagUpdate(1)              # wake the download worker
        appsettingFlagUpdate('meta_que_switch', 1)     # wake the metadata worker

    if pk and scene_ID > 0 and not scene_link_exists(media_type, scene_ID, pk):
        if media_type == 'music':
            CRUD_tblMusicScene([scene_ID, pk, 1, 100], "C")
        else:
            CRUD_tblVideoScene([scene_ID, pk, 0, 1, 100, 0], "C")
    return pk, created, ''


def _enqueue_legacy(url, mediaType, scene_ID, flname):
    """Old behavior for non-parseable URLs: name-based file, no dedup."""
    import re as _re
    from pathlib import Path as _Path
    # Only HERE does flname become a filename (no video id to name the file
    # after) — scrub it. The id-based path keeps the raw text as a human
    # displayName override, so callers no longer pre-sanitize.
    flname = _re.sub('[^A-Za-z0-9._-]', '_', flname)
    title = flname + '.' + mediaType
    if mediaType == 'mp3':
        path = str(_Path.home()) + "/Music/SP/"
        pk = CRUD_tblMusic([path, title, 0, '', 1, 0, 0, url, 1], "C")
        if scene_ID > 0:
            CRUD_tblMusicScene([scene_ID, pk, 1, 100], "C")
    else:
        path = str(_Path.home()) + "/Videos/SP/"
        pk = CRUD_tblvideomedia([path, title, 0, '', 1, 0, 0, url, 1], "C")
        if scene_ID > 0:
            CRUD_tblVideoScene([scene_ID, pk, 0, 1, 100, 0], "C")
    appsettingYT_QuePlayFlagUpdate(1)
    # Metadata rides along with the download here too: yt-dlp extraction works
    # for any supported site, not just YouTube (the id-based path sets
    # metaStatus=1 in its INSERT). The CRUD insert leaves it at the default 0.
    if url:
        set_meta_status('music' if mediaType == 'mp3' else 'video', pk, 1)
        appsettingFlagUpdate('meta_que_switch', 1)
    return pk


def _set_dnload_status(media_type, pk, status):
    if media_type == 'music':
        CRUD_tblMusic([pk, status], "dnUpdate")
    else:
        CRUD_tblvideomedia([pk, status], "dnUpdate")


def update_dn_last_error(tbl, pk, err):
    """Store (or clear with '') the last download error on a media row.
    `tbl` is the raw table name the download queue carries ('tblMusic' /
    'tblVideoMedia') — same identifier YT_Exec already switches on."""
    pkcol = 'song_id' if tbl == 'tblMusic' else 'video_ID'
    table = 'tblMusic' if tbl == 'tblMusic' else 'tblVideoMedia'
    conn = sqlite3.connect(database)
    c = conn.cursor()
    c.execute(f"UPDATE {table} SET dnLastError = ? WHERE {pkcol} = ?", (err, pk))
    conn.commit()
    c.close()
    conn.close()


def set_meta_status(media_type, pk, status, next_retry=None):
    tbl, pkcol, _ = _media_cols(media_type)
    conn = sqlite3.connect(database)
    c = conn.cursor()
    c.execute(f"UPDATE {tbl} SET metaStatus = ?, metaNextRetry = ? WHERE {pkcol} = ?",
              (status, next_retry, pk))
    conn.commit()
    c.close()
    conn.close()


def requeue_metadata_if_missing(media_type, pk):
    """Re-queue metadata extraction for a row that has none — never extracted
    (0) or failed out of retries (4). Rides along wherever a download is
    re-queued (table Download Status flip, re-adding a known video) so the two
    recover together. No-op for finished (3), queued/processing (1/2),
    permanently unavailable (5), and rows with no urlSource to extract from.
    Resets the stored retry_count so the row gets a full set of fresh attempts,
    not the single one left over from the failed run."""
    tbl, pkcol, _ = _media_cols(media_type)
    conn = sqlite3.connect(database)
    c = conn.cursor()
    c.execute(f"UPDATE {tbl} SET metaStatus = 1, metaNextRetry = NULL "
              f"WHERE {pkcol} = ? AND metaStatus IN (0, 4) "
              f"AND urlSource IS NOT NULL AND urlSource <> ''", (pk,))
    changed = c.rowcount
    if changed:
        c.execute("UPDATE tblMediaMetadata SET retry_count = 0 WHERE media_type = ? AND media_id = ?",
                  (media_type, pk))
    conn.commit()
    c.close()
    conn.close()
    if changed:
        appsettingFlagUpdate('meta_que_switch', 1)
    return bool(changed)


def fill_display_name_if_empty(media_type, pk, name):
    """Atomic fill: a user-typed override is never clobbered by metadata —
    the CASE runs inside one UPDATE, so there is no read-then-write race."""
    tbl, pkcol, _ = _media_cols(media_type)
    conn = sqlite3.connect(database)
    c = conn.cursor()
    c.execute(f"UPDATE {tbl} SET displayName = CASE WHEN displayName IS NULL OR displayName = '' THEN ? ELSE displayName END WHERE {pkcol} = ?",
              (name, pk))
    conn.commit()
    c.close()
    conn.close()


def select_Meta_Que_Next():
    """One queued metadata job whose backoff (if any) has expired.
    Returns [(pkey, urlSource, media_type, retry_count)] or []."""
    conn = sqlite3.connect(database)
    c = conn.cursor()
    c.execute("Select * from ( \
                 Select song_id as pkey, urlSource, 'music' as media_type, \
                        COALESCE((Select retry_count from tblMediaMetadata mm where mm.media_type='music' and mm.media_id=song_id),0) as retry_count, \
                        metaNextRetry \
                   from tblMusic where urlSource not null and urlSource <> '' and metaStatus = 1 \
               union \
                 Select video_ID as pkey, urlSource, 'video' as media_type, \
                        COALESCE((Select retry_count from tblMediaMetadata mm where mm.media_type='video' and mm.media_id=video_ID),0) as retry_count, \
                        metaNextRetry \
                   from tblVideoMedia where urlSource not null and urlSource <> '' and metaStatus = 1 \
               ) where metaNextRetry IS NULL or metaNextRetry <= datetime('now') \
               Order By RANDOM(), pkey ASC LIMIT 1;")
    data = c.fetchall()
    c.close()
    conn.close()
    return data


def upsert_media_metadata(media_type, media_id, fields):
    """Create-or-update the tblMediaMetadata row for (media_type, media_id).
    `fields` is a dict of column -> value (promoted columns / raw_json /
    retry_count / last_error / extracted_at)."""
    conn = sqlite3.connect(database)
    c = conn.cursor()
    c.execute("SELECT metadata_id FROM tblMediaMetadata WHERE media_type = ? AND media_id = ?",
              (media_type, media_id))
    row = c.fetchone()
    if row:
        sets = ', '.join(f"{k} = ?" for k in fields)
        c.execute(f"UPDATE tblMediaMetadata SET {sets} WHERE metadata_id = ?",
                  (*fields.values(), row[0]))
        rid = row[0]
    else:
        cols = ', '.join(fields)
        marks = ', '.join('?' for _ in fields)
        c.execute(f"INSERT INTO tblMediaMetadata(media_type, media_id, {cols}) VALUES (?, ?, {marks})",
                  (media_type, media_id, *fields.values()))
        rid = c.lastrowid
    conn.commit()
    c.close()
    conn.close()
    return rid


def scene_link_exists(media_type, scene_ID, media_pk):
    """True if this scene already links this media row — prevents duplicate
    links (which would make the item play twice per cycle)."""
    conn = sqlite3.connect(database)
    c = conn.cursor()
    if media_type == 'music':
        c.execute("SELECT 1 FROM tblMusicScene WHERE scene_ID = ? AND song_ID = ? LIMIT 1",
                  (scene_ID, media_pk))
    else:
        c.execute("SELECT 1 FROM tblVideoScene WHERE scene_ID = ? AND video_ID = ? LIMIT 1",
                  (scene_ID, media_pk))
    row = c.fetchone()
    c.close()
    conn.close()
    return row is not None


def delete_media_row(media_type, pk):
    """Remove a media row ENTIRELY: its scene-links, metadata row, DB row and
    on-disk file. With videoId dedup a row (and its one file) can be shared by
    many scenes, so per-scene removal is deleting the scene-LINK; this is the
    'remove from everywhere' operation. Returns the number of scene links removed."""
    tbl, pkcol, namecol = _media_cols(media_type)
    conn = sqlite3.connect(database)
    c = conn.cursor()
    c.execute(f"SELECT (path || {namecol}) FROM {tbl} WHERE {pkcol} = ?", (pk,))
    frow = c.fetchone()
    if media_type == 'music':
        c.execute("SELECT COUNT(*) FROM tblMusicScene WHERE song_ID = ?", (pk,))
        links = c.fetchone()[0]
        c.execute("DELETE FROM tblMusicScene WHERE song_ID = ?", (pk,))
    else:
        c.execute("SELECT COUNT(*) FROM tblVideoScene WHERE video_ID = ?", (pk,))
        links = c.fetchone()[0]
        c.execute("DELETE FROM tblVideoScene WHERE video_ID = ?", (pk,))
    c.execute("DELETE FROM tblMediaMetadata WHERE media_type = ? AND media_id = ?", (media_type, pk))
    c.execute(f"DELETE FROM {tbl} WHERE {pkcol} = ?", (pk,))
    conn.commit()
    c.close()
    conn.close()
    if frow and frow[0]:
        try:
            os.remove(frow[0])
        except OSError:
            pass  # file already gone / never downloaded
    return links


def scan_missing_media():
    """Utilities 'Scan Media Files': re-queue any downloadable row whose file is
    missing from disk, so imported/merged data (or files deleted outside the
    app) gets downloaded through the normal pipeline.

    Per-status behaviour: Finished(3) with a missing file and Failed(4) go back
    to Queued(1); Processing(2) is mid-download and left alone; Queued(1)
    already is; Unavailable(5) is permanent; legacy rows (no urlSource) have
    nothing to download from. Returns {'music': n, 'video': n}."""
    conn = sqlite3.connect(database)
    c = conn.cursor()
    out = {'music': 0, 'video': 0}
    for kind, tbl, pkcol, namecol in (('music', 'tblMusic', 'song_id', 'song'),
                                      ('video', 'tblVideoMedia', 'video_ID', 'title')):
        c.execute(f"SELECT {pkcol}, path || {namecol}, dnLoadStatus FROM {tbl} "
                  f"WHERE urlSource IS NOT NULL AND urlSource <> '' AND dnLoadStatus IN (3, 4)")
        for pk, full, status in c.fetchall():
            if status == 3 and full and os.path.exists(full):
                continue                     # downloaded and present — fine
            c.execute(f"UPDATE {tbl} SET dnLoadStatus = 1 WHERE {pkcol} = ?", (pk,))
            out[kind] += 1
    conn.commit()
    c.close()
    conn.close()
    if out['music'] or out['video']:
        appsettingYT_QuePlayFlagUpdate(1)    # wake the downloader
    return out


def recover_stuck_processing():
    """Boot sweep: re-queue any metadata/playlist job left at 'Processing' (2) by
    a crash or power loss mid-job. The queue selectors only pick status 1, so
    without this a stranded row would never be retried. Safe at boot — the
    workers that could legitimately hold status 2 haven't started yet."""
    conn = sqlite3.connect(database)
    c = conn.cursor()
    n = 0
    for tbl, col in (('tblMusic', 'metaStatus'), ('tblVideoMedia', 'metaStatus'),
                     ('tblPlaylistQueue', 'status')):
        try:
            c.execute(f"UPDATE {tbl} SET {col} = 1 WHERE {col} = 2")
            n += c.rowcount
        except sqlite3.OperationalError:
            pass  # table/column not migrated yet (first boot ordering)
    conn.commit()
    c.close()
    conn.close()
    return n


def get_now_playing():
    """Dashboard snapshot: the playing song/video (ids written to the
    currentsong/currentvideo appsettings by the player processes at play start,
    zeroed on queue-drain/stop) resolved to human names, plus the active scene."""
    conn = sqlite3.connect(database)
    c = conn.cursor()
    c.execute("SELECT name, value FROM tblAppSettings WHERE name IN ('currentsong','currentvideo','CurrentScene')")
    vals = {r[0]: r[1] for r in c.fetchall()}

    def _as_int(v):
        try:
            return int(v)
        except (TypeError, ValueError):
            return 0

    out = {'song': None, 'video': None, 'scene': None}
    scn = _as_int(vals.get('CurrentScene'))
    sid = _as_int(vals.get('currentsong'))
    if sid > 0:
        # thumbnail rides along from tblMediaMetadata (NULL until extracted) so
        # the now-playing bar can show art + metadata hover; loops comes from
        # the active scene's link row (--loop-file=N → N+1 plays) so the bar
        # can flag looped media.
        c.execute("SELECT COALESCE(NULLIF(m.displayName,''), m.song), md.thumbnail, "
                  "COALESCE(ms.loops, 0) "
                  "FROM tblMusic m LEFT JOIN tblMediaMetadata md "
                  "ON md.media_type='music' AND md.media_id=m.song_ID "
                  "LEFT JOIN tblMusicScene ms "
                  "ON ms.song_ID = m.song_ID AND ms.scene_ID = ? "
                  "WHERE m.song_ID = ?", (scn, sid))
        row = c.fetchone()
        if row:
            out['song'] = {'id': sid, 'name': row[0], 'thumbnail': row[1], 'loops': row[2]}
    vid = _as_int(vals.get('currentvideo'))
    if vid > 0:
        c.execute("SELECT COALESCE(NULLIF(v.displayName,''), v.title), md.thumbnail, "
                  "COALESCE(vs.loops, 0) "
                  "FROM tblVideoMedia v LEFT JOIN tblMediaMetadata md "
                  "ON md.media_type='video' AND md.media_id=v.video_ID "
                  "LEFT JOIN tblVideoScene vs "
                  "ON vs.video_ID = v.video_ID AND vs.scene_ID = ? "
                  "WHERE v.video_ID = ?", (scn, vid))
        row = c.fetchone()
        if row:
            out['video'] = {'id': vid, 'name': row[0], 'thumbnail': row[1], 'loops': row[2]}
    if scn > 0:
        c.execute("SELECT sceneName FROM tblScenes WHERE scene_ID = ?", (scn,))
        row = c.fetchone()
        if row:
            out['scene'] = {'id': scn, 'name': row[0]}
    c.close()
    conn.close()
    return out


def appsettingSetCurrentScene(scene_id):
    """Record the ACTIVE scene so playback picks the right per-scene
    volume/order/screen/loops for media rows shared across scenes."""
    conn = sqlite3.connect(database)
    c = conn.cursor()
    c.execute("SELECT 1 FROM tblAppSettings WHERE name = 'CurrentScene'")
    if c.fetchone():
        c.execute("UPDATE tblAppSettings SET value = ? WHERE name = 'CurrentScene'", (str(scene_id),))
    else:
        c.execute("INSERT INTO tblAppSettings(name, value, typevalue) VALUES ('CurrentScene', ?, 'int')",
                  (str(scene_id),))
    conn.commit()
    c.close()
    conn.close()


def appsettingGetCurrentScene():
    val = appsettingFlagGet('CurrentScene')
    try:
        return int(val)
    except (TypeError, ValueError):
        return 0


# ---------------------------------------------------------------------------
# Playlist queue helpers
# ---------------------------------------------------------------------------

def enqueue_playlist(url, media_type, scene_ID):
    conn = sqlite3.connect(database)
    c = conn.cursor()
    now = str(datetime.fromtimestamp(time.time()).strftime('%Y-%m-%d %H:%M:%S'))
    c.execute("INSERT INTO tblPlaylistQueue(url, media_type, scene_ID, status, retry_count, last_error, created_at) VALUES (?, ?, ?, 1, 0, '', ?)",
              (url, media_type, scene_ID, now))
    conn.commit()
    rid = c.lastrowid
    c.close()
    conn.close()
    appsettingFlagUpdate('playlist_que_switch', 1)
    return rid


def backfill_video_ids():
    """One-shot: tag legacy rows with the videoId parsed from urlSource and queue
    them for metadata. Only the LOWEST-pk row per video is tagged (the partial
    UNIQUE index forbids two rows sharing a videoId) — pre-dedup duplicates are
    left with videoId NULL and reported, so nothing is merged/deleted silently.
    Returns a summary dict. Skips manual rows (empty urlSource)."""
    from ytid import youtube_video_id
    summary = {'tagged': 0, 'duplicates_skipped': 0, 'unparseable': 0, 'duplicates': []}
    conn = sqlite3.connect(database)
    c = conn.cursor()
    for media_type, tbl, pk, namecol in (('music', 'tblMusic', 'song_id', 'song'),
                                         ('video', 'tblVideoMedia', 'video_ID', 'title')):
        c.execute(f"SELECT {pk}, urlSource FROM {tbl} WHERE urlSource IS NOT NULL AND urlSource <> '' AND (videoId IS NULL OR videoId = '') ORDER BY {pk} ASC")
        rows = c.fetchall()
        seen = set()
        for rid, url in rows:
            vid = youtube_video_id(url)
            if not vid:
                summary['unparseable'] += 1
                continue
            # already tagged on a prior row this run, or on an existing row?
            c.execute(f"SELECT {pk} FROM {tbl} WHERE videoId = ? LIMIT 1", (vid,))
            if vid in seen or c.fetchone():
                summary['duplicates_skipped'] += 1
                summary['duplicates'].append({'media_type': media_type, pk: rid, 'videoId': vid})
                continue
            c.execute(f"UPDATE {tbl} SET videoId = ?, metaStatus = 1 WHERE {pk} = ?", (vid, rid))
            seen.add(vid)
            summary['tagged'] += 1
        conn.commit()
    c.close()
    conn.close()
    if summary['tagged']:
        appsettingFlagUpdate('meta_que_switch', 1)
    return summary


def select_Playlist_Que_Next():
    """One queued playlist job whose retry backoff (if any) has expired —
    mirrors select_Meta_Que_Next so a transient expansion failure waits out
    its backoff instead of burning all retries seconds apart."""
    conn = sqlite3.connect(database)
    c = conn.cursor()
    c.execute("SELECT playlist_id, url, media_type, scene_ID, retry_count FROM tblPlaylistQueue "
              "WHERE status = 1 AND (next_retry IS NULL OR next_retry <= datetime('now')) "
              "ORDER BY playlist_id ASC LIMIT 1")
    data = c.fetchall()
    c.close()
    conn.close()
    return data


def update_playlist_status(playlist_id, status, retry_count=None, last_error=None, next_retry=None):
    """next_retry is written unconditionally: set on a transient re-queue,
    cleared (NULL) on every other transition so a job never carries a stale
    backoff into Processing/Finished/Failed."""
    conn = sqlite3.connect(database)
    c = conn.cursor()
    c.execute("UPDATE tblPlaylistQueue SET status = ?, retry_count = COALESCE(?, retry_count), "
              "last_error = COALESCE(?, last_error), next_retry = ? WHERE playlist_id = ?",
              (status, retry_count, last_error, next_retry, playlist_id))
    conn.commit()
    c.close()
    conn.close()


def meta_pending_any():
    """True if ANY media row is queued for metadata (metaStatus 1), INCLUDING
    rows whose retry backoff hasn't expired. The worker must not switch itself
    off while one of these waits — select_Meta_Que_Next excludes backoff rows,
    so 'nothing selectable' does not mean 'nothing pending'."""
    conn = sqlite3.connect(database)
    c = conn.cursor()
    c.execute("SELECT EXISTS(SELECT 1 FROM tblMusic WHERE urlSource IS NOT NULL AND urlSource <> '' AND metaStatus = 1) "
              "OR EXISTS(SELECT 1 FROM tblVideoMedia WHERE urlSource IS NOT NULL AND urlSource <> '' AND metaStatus = 1)")
    row = c.fetchone()
    c.close()
    conn.close()
    return bool(row and row[0])


def playlist_pending_any():
    """Playlist-queue twin of meta_pending_any (status 1, backoff included)."""
    conn = sqlite3.connect(database)
    c = conn.cursor()
    c.execute("SELECT EXISTS(SELECT 1 FROM tblPlaylistQueue WHERE status = 1)")
    row = c.fetchone()
    c.close()
    conn.close()
    return bool(row and row[0])




def appsettingVideoPlayFlag():
    conn = sqlite3.connect(database)
    #conn.text_factory = lambda x: unicode(x, 'utf-8', 'ignore')
    c = conn.cursor()
    c.execute("SELECT * FROM tblAppSettings where name =  'playvideoswitch'")    
    data = c.fetchall()
    conn.commit()
    c.close()
    conn.close()
    #for r in data:
    #   row = r
    return data

def appsettingYT_QuePID():
    conn = sqlite3.connect(database)
    #conn.text_factory = lambda x: unicode(x, 'utf-8', 'ignore')
    c = conn.cursor()
    c.execute("SELECT * FROM tblAppSettings where name =  'yt_que_PID'")    
    data = c.fetchall()
    conn.commit()
    c.close()
    conn.close()
    #for r in data:
    #   row = r
    return data


def appsettingGetCampaignSelected():
    conn = sqlite3.connect(database)
    #conn.text_factory = lambda x: unicode(x, 'utf-8', 'ignore')
    c = conn.cursor()
    c.execute("select value from tblAppSettings where name = 'ShowCampaign'")
    data = c.fetchall()
    conn.commit()
    c.close()
    conn.close()
    # Fresh install / unseeded setting: guarantee callers a valid [0][0] default
    if not data or data[0][0] is None:
        return [(0,)]
    return data

def appsettingGetSceneFilter():
    conn = sqlite3.connect(database)
    #conn.text_factory = lambda x: unicode(x, 'utf-8', 'ignore')
    c = conn.cursor()
    c.execute("select value from tblAppSettings where name = 'SceneFilter'")
    data = c.fetchall()
    conn.commit()
    c.close()
    conn.close()
    # Fresh install / unseeded setting: guarantee callers a valid [0][0] default
    if not data or data[0][0] is None:
        return [(0,)]
    return data

def appsettingSetSceneFilter(val):
    conn = sqlite3.connect(database)
    #conn.text_factory = lambda x: unicode(x, 'utf-8', 'ignore')
    c = conn.cursor()
    c.execute("Update tblAppSettings set value = ?  where name =  'SceneFilter'",(val,))    
    conn.commit()
    c.close()
    conn.close()

def appsettingGetNotCampaignSelected():
    conn = sqlite3.connect(database)
    #conn.text_factory = lambda x: unicode(x, 'utf-8', 'ignore')
    c = conn.cursor()
    c.execute("Select campaign_id from tblCampaigns where campaign_id not in (select value from tblAppSettings where name = 'ShowCampaign')")
    data = c.fetchall()
    conn.commit()
    c.close()
    conn.close()
    #for r in data:
    #   row = r
    return data




def CRUD_tblCampaigns(row,CRUD):
    conn = sqlite3.connect(database)
    #conn.text_factory = lambda x: unicode(x, 'utf-8', 'ignore')
    c = conn.cursor()
    unix = time.time()
    if CRUD == "C":
        _campaign_name = row[0]  
        _active = row[1]
        _order_by = row[2]
        c.execute("Insert INTO tblCampaigns(campaign_name, active,order_by) VALUES (?, ?, ?)",(_campaign_name, _active, _order_by))
        conn.commit()
        return c.lastrowid
    elif CRUD == "R":
        _id = row[0]
        c.execute("SELECT * FROM tblCampaigns where campaign_id = ?", (_id,))
        data = c.fetchall()
        conn.commit()
        return data
    elif CRUD == "U":
        _id = row[0]
        _campaign_name = row[1]  
        _active = row[2]
        _order_by = row[3]
        c.execute("Update tblCampaigns set campaign_name = ?, active = ?, order_by = ? where campaign_id = ?",(_campaign_name, _active, _order_by, _id)) 
        conn.commit()
        return _id
    elif CRUD == "D":
        _id = row[0]
        c.execute("Delete from tblCampaigns where campaign_id = ?", (_id,))
        conn.commit()
        return _id
    elif CRUD == "Selected":
        c.execute("select c.campaign_id, c.campaign_name from tblCampaigns c where c.active = 1 order by c.order_by")
        data = c.fetchall()
        conn.commit()
        return data
    c.close()
    conn.close()    

def appsettingSetCampaignSelected(val):
    conn = sqlite3.connect(database)
    #conn.text_factory = lambda x: unicode(x, 'utf-8', 'ignore')
    c = conn.cursor()
    c.execute("Update tblAppSettings set value = ?  where name =  'ShowCampaign'",(val,))    
    conn.commit()
    c.close()
    conn.close()
    



def appsettingAudioPlayFlag():
    conn = sqlite3.connect(database)
    #conn.text_factory = lambda x: unicode(x, 'utf-8', 'ignore')
    c = conn.cursor()
    c.execute("SELECT * FROM tblAppSettings where name =  'playsongswitch'")    
    data = c.fetchall()
    conn.commit()
    c.close()
    conn.close()
    #for r in data:
    #   row = r
    return data

def appsettingAudioPlayPID():
    conn = sqlite3.connect(database)
    #conn.text_factory = lambda x: unicode(x, 'utf-8', 'ignore')
    c = conn.cursor()
    c.execute("SELECT * FROM tblAppSettings where name =  'playsongPID'")    
    data = c.fetchall()
    conn.commit()
    c.close()
    conn.close()
    #for r in data:
    #   row = r
    return data

def appsettingVideoPlayPID():
    conn = sqlite3.connect(database)
    #conn.text_factory = lambda x: unicode(x, 'utf-8', 'ignore')
    c = conn.cursor()
    c.execute("SELECT * FROM tblAppSettings where name =  'playvideoPID'")    
    data = c.fetchall()
    conn.commit()
    c.close()
    conn.close()
    #for r in data:
    #   row = r
    return data

def appsettingVideoPlayFlagUpdate(val):
    conn = sqlite3.connect(database)
    #conn.text_factory = lambda x: unicode(x, 'utf-8', 'ignore')
    c = conn.cursor()
    c.execute("Update tblAppSettings set value = ?  where name =  'playvideoswitch'",(val,))    
    conn.commit()
    c.close()
    conn.close()
    
def appsettingVideoPlayFlagUpdatePID(val):
    conn = sqlite3.connect(database)
    #conn.text_factory = lambda x: unicode(x, 'utf-8', 'ignore')
    c = conn.cursor()
    c.execute("Update tblAppSettings set value = ?  where name =  'playvideoPID'",(val,))    
    conn.commit()
    c.close()
    conn.close()
    
def appsettingAudioPlayFlagUpdate(val):
    conn = sqlite3.connect(database)
    #conn.text_factory = lambda x: unicode(x, 'utf-8', 'ignore')
    c = conn.cursor()
    c.execute("Update tblAppSettings set value = ?  where name =  'playsongswitch'",(val,))    
    conn.commit()
    c.close()
    conn.close()
    
def appsettingGetKeepMusicPlaying():
    conn = sqlite3.connect(database)
    c = conn.cursor()
    c.execute("SELECT value FROM tblAppSettings where name = 'KeepMusicPlaying'")
    row = c.fetchone()
    c.close()
    conn.close()
    return int(row[0]) if row else 0

def appsettingGet(name, default=None):
    conn = sqlite3.connect(database)
    c = conn.cursor()
    c.execute("SELECT value FROM tblAppSettings WHERE name = ?", (name,))
    row = c.fetchone()
    c.close()
    conn.close()
    return row[0] if row else default

def appsettingSet(name, value, typevalue='text'):
    conn = sqlite3.connect(database)
    c = conn.cursor()
    c.execute("SELECT count(*) FROM tblAppSettings WHERE name = ?", (name,))
    exists = c.fetchone()[0] > 0
    if exists:
        c.execute("UPDATE tblAppSettings SET value = ? WHERE name = ?", (str(value), name))
    else:
        c.execute("INSERT INTO tblAppSettings(name, value, typevalue) VALUES (?, ?, ?)",
                  (name, str(value), typevalue))
    conn.commit()
    c.close()
    conn.close()

def appsettingSetKeepMusicPlaying(val):
    conn = sqlite3.connect(database)
    c = conn.cursor()
    c.execute("SELECT count(*) FROM tblAppSettings where name = 'KeepMusicPlaying'")
    if c.fetchone()[0] == 0:
        c.execute("INSERT INTO tblAppSettings(name, value, typevalue) VALUES ('KeepMusicPlaying', ?, 'int')", (val,))
    else:
        c.execute("UPDATE tblAppSettings set value = ? where name = 'KeepMusicPlaying'", (val,))
    conn.commit()
    c.close()
    conn.close()

def appsettingAudioPlayFlagUpdatePID(val):
    conn = sqlite3.connect(database)
    #conn.text_factory = lambda x: unicode(x, 'utf-8', 'ignore')
    c = conn.cursor()
    c.execute("Update tblAppSettings set value = ?  where name =  'playsongPID'",(val,))    
    conn.commit()
    c.close()
    conn.close()

def dict_factory(cursor, row):
    d = {}
    for idx, col in enumerate(cursor.description):
        d[col[0]] = row[idx]
    return d
def combine_rows(rows):
    combined_row = {}
    for row in rows:
        for key, value in row.items():
            # If value is None and the key exists in combined_row, skip
            # Otherwise, update the combined_row with non-null value
            if combined_row.get(key) is None and value is not None:
                combined_row[key] = value
            elif key not in combined_row:
                combined_row[key] = value
    return combined_row



def get_Scenes():
    conn = sqlite3.connect(database)
    #conn.text_factory = lambda x: unicode(x, 'utf-8', 'ignore')
    
    
    camppaignids = "("
    testCampaignID = appsettingGetCampaignSelected()
    try:
        selectedCampaign = int(testCampaignID[0][0])
    except (IndexError, TypeError, ValueError):
        selectedCampaign = 0
    if selectedCampaign != 0:
        campaignsNotSelected = appsettingGetNotCampaignSelected()
        if len(campaignsNotSelected) != 0:
            for row in campaignsNotSelected:
                camppaignids = camppaignids + str(row[0]) + ","
            camppaignids = camppaignids[:-1] + ")"
    else:
        camppaignids = camppaignids + "0)"
    #print(camppaignids)
    c = conn.cursor()
    
    c.row_factory = dict_factory
    
    c.execute("select s.scene_ID, substr(s.sceneName,0,16) AS sceneName, dt.scenePattern_ID,  dt.color, UPPER(substr(dt.modelName,0,16)) as modelName , dt.wledPattern_ID,  dt.color1, UPPER(substr(dt.effectName,0,16)) as effectName,  dt.musicScene_ID,  dt.videoScene_ID, s.orderby from ( \
                    select sp.scene_ID , sp.scenePattern_ID, substr(sp.color, 2, LENGTH(sp.color)-2) as color, l.modelName, NULL as wledPattern_ID, null as color1, NULL as effectName, NULL as musicScene_ID, NULL as videoScene_ID  from tblScenePattern sp \
                        join tblLEDTypeModel l on SP.ledTypeModel_ID = l.ledTYpeMOdel_ID where sp.scene_ID <> 0 \
                union \
                    select  wl.scene_ID, NULL as scenePattern_ID,null as color, NULL as modelName, wl.wledPattern_ID, substr(wl.color1, 2, LENGTH(wl.color1)-2) as color1, case when instr(effectName, '@') = 0 THEN effectName ELSE substr(effectName,1, instr(effectName, '@')-1) END  as effectName, NULL as musicScene_ID, NULL as videoScene_ID from tblwledPattern wl \
                        join tblEffect e on e.ef_ID = wl.effect where wl.scene_ID <> 0 \
                union \
                    select  ms.scene_ID, NULL as scenePattern_ID,null as color, NULL as modelName, NULL as wledPattern_ID, null as color1, NULL as effectName, ms.musicScene_ID, NULL as videoScene_ID from tblMusicScene ms where ms.scene_ID <> 0 \
                union \
                    select vs.scene_ID, NULL as scenePattern_ID,null as color, NULL as modelName, NULL as wledPattern_ID, null as color1, NULL as effectName, NULL as musicScene_ID, vs.videoScene_ID from tblvideoScene vs where vs.scene_ID <> 0 ) dt \
                    join tblScenes s on s.scene_ID = dt.scene_ID where s.campaign_id NOT IN "+str(camppaignids)+ " and s.active = 1 order by s.orderby,dt.color desc,dt.modelName desc,dt.color1 desc,dt.effectName desc;")


    dataPre = c.fetchall()
    #print(dataPre)
    grouped_data = defaultdict(list)
    for row in dataPre:
        grouped_data[row['scene_ID']].append(row)
    data = [combine_rows(rows) for rows in grouped_data.values()]
    
    conn.commit()
    c.close()
    conn.close()
    #for r in data:
    #   row = r
    
    return data

def getAllIPAddressFromtblServersIP(ips):
    conn = sqlite3.connect(database)
    c = conn.cursor()
    unix = time.time()
    c.execute("SELECT * FROM tblServersIP where ipAddress =  ?",(str(ips),))
    data = c.fetchall()
    conn.commit()
    c.close()
    conn.close()
    return data

def CRUD_tblvideomedia(row,CRUD):
    conn = sqlite3.connect(database)
    #conn.text_factory = lambda x: unicode(x, 'utf-8', 'ignore')
    c = conn.cursor()
    unix = time.time()
    if CRUD == "C": 
        _path = str(row[0])
        _title = row[1]
        _pTimes = row[2]
        _playedDTTM = row[3]
        _active = row[4]
        _genre = row[5]
        _que = row[6]
        _urlSource = row[7]
        _dnLoadStatus = row[8]
        c.execute("Insert INTO tblVideoMedia(path, title, pTimes, playedDTTM, active, genre, que,urlSource, dnLoadStatus) VALUES (?, ?, ?, ?, ?, ?, ?,?, ?)",( _path, _title, _pTimes, _playedDTTM, _active, _genre,_que, _urlSource, _dnLoadStatus))
        conn.commit()
        return c.lastrowid
    elif CRUD == "R":
        _id = row[0]
        c.execute("SELECT * FROM tblVideoMedia where id = ?", (_id,))
        data = c.fetchall()
        conn.commit()
        return data
    elif CRUD == "U":
        _id = row[0]
        _path= row[1]
        _title = row[2]
        _pTimes = row[3]
        _playedDTTM = row[4]
        _active = row[5]
        _genre = row[6]
        _urlSource = row[7]
        _dnLoadStatus = row[8]
        c.execute("UPDATE tblVideoMedia SET path = ?, title = ?, pTimes = ?, playedDTTM = ?, active = ?, genre = ?, urlSource = ?, dnLoadStatus = ?  where video_id = ?" ,( _path,_title, _pTimes, _playedDTTM, _active, _genre, _urlSource, _dnLoadStatus,  _id))
        conn.commit()
    elif CRUD == "D":
        _id = row[0]
        #print("id",_id)
        c.execute("Delete From tblVideoMedia where video_id = ?", (_id,))
        conn.commit()
    elif CRUD == "dnUpdate":
        _id = row[0]
        _dnLoadStatus = row[1]
        c.execute("UPDATE tblVideoMedia SET dnLoadStatus = ?  where video_id = ?" ,( _dnLoadStatus,  _id))
        conn.commit()
    else:
        c.execute("SELECT * FROM tblVideoMedia order by title")
        data = c.fetchall()
        conn.commit()
        return data
    c.close()
    conn.close()

def CRUD_tblMusic(row,CRUD):
    conn = sqlite3.connect(database)
    #conn.text_factory = lambda x: unicode(x, 'utf-8', 'ignore')
    c = conn.cursor()
    unix = time.time()
    if CRUD == "C": 
        _path = str(row[0])
        _song = row[1]
        _pTimes = row[2]
        _playedDTTM = row[3]
        _active = row[4]
        _genre = row[5]
        _que = row[6]
        _urlSource = row[7]
        _dnLoadStatus = row[8]
        c.execute("Insert INTO tblmusic(path, song, pTimes, playedDTTM, active, genre, que,urlSource, dnLoadStatus) VALUES (?, ?, ?, ?, ?, ?, ?,?, ?)",( _path, _song, _pTimes, _playedDTTM, _active, _genre,_que, _urlSource, _dnLoadStatus))
        conn.commit()
        return c.lastrowid
    elif CRUD == "R":
        _id = row[0]
        c.execute("SELECT * FROM tblmusic where id = ?", (_id,))
        data = c.fetchall()
        conn.commit()
        return data
    elif CRUD == "U":
        _id = row[0]
        _path= row[1]
        _song = row[2]
        _pTimes = row[3]
        _playedDTTM = row[4]
        _active = row[5]
        _genre = row[6]
        _urlSource = row[7]
        _dnLoadStatus = row[8]
        c.execute("UPDATE tblmusic SET   path = ?, song = ?, pTimes = ?, playedDTTM = ?, active = ?, genre = ?, urlSource = ?, dnLoadStatus = ?  where song_id = ?" ,( _path,_song, _pTimes, _playedDTTM, _active, _genre, _urlSource, _dnLoadStatus,  _id))
        conn.commit()
    elif CRUD == "D":
        _id = row[0]
        #print("id",_id)
        c.execute("Delete From tblmusic where song_id = ?", (_id,))
        conn.commit()
    elif CRUD == "dnUpdate":
        _id = row[0]
        _dnLoadStatus = row[1]
        c.execute("UPDATE tblmusic SET  dnLoadStatus = ?  where song_id = ?" ,( _dnLoadStatus,  _id))
        conn.commit()
    else:
        c.execute("SELECT * FROM tblmusic ORDER BY song")
        data = c.fetchall()
        conn.commit()
        return data
    c.close()
    conn.close()

def CRUD_tblAppSettings(row,CRUD):
    conn = sqlite3.connect(database)
    #conn.text_factory = lambda x: unicode(x, 'utf-8', 'ignore')
    c = conn.cursor()
    unix = time.time()
    if CRUD == "C":
        _name = row[0]  
        _value = str(row[1])
        _typevalue = row[2]
        c.execute("Insert INTO tblAppSettings(name, value, typevalue) VALUES (?, ?, ?)",(_name, _value, _typevalue))
        conn.commit()
        return c.lastrowid
    elif CRUD == "R":
        _id = row[0]
        c.execute("SELECT * FROM tblAppSettings where id = ?", (_id,))
        data = c.fetchall()
        conn.commit()
        return data
    elif CRUD == "U":
        _id = row[0]
        _name = row[1]
        _value= row[2]
        _typevalue = row[3]
        c.execute("UPDATE tblAppSettings SET  name = ?, value= ?, typevalue = ?  where id = ?" ,( _name, _value,_typevalue,  _id))
        conn.commit()
    elif CRUD == "D":
        _id = row[0]
        c.execute("Delete From tblAppSettings where id = ?", (_id,))
        conn.commit()
    elif CRUD == "DA":
        _id = row[0]
        c.execute("Delete From tblAppSettings")
        conn.commit()
    elif CRUD == "byName":
        _id = row[0]
        c.execute("select * From tblAppSettings where name = ?", (_id,))
        data = c.fetchall()
        conn.commit()
        return data
    else:
        c.execute("SELECT * FROM tblAppSettings")
        data = c.fetchall()
        conn.commit()
        return data
    c.close()
    conn.close()

def CRUD_tblServerRole(row,CRUD):
    conn = sqlite3.connect(database)
    #conn.text_factory = lambda x: unicode(x, 'utf-8', 'ignore')
    c = conn.cursor()
    unix = time.time()
    if CRUD == "C":
        _name = row[0] 
        _active = row[1]
        _orderBy = row[2]
        c.execute("Insert INTO tblServerRole(name, active, orderBy) VALUES (?, ?, ?)",(_name, _active, _orderBy))
        conn.commit()
        return c.lastrowid
    elif CRUD == "R":
        _ID = row[0]
        c.execute("SELECT * FROM tblServerRole where ID = ?", (_ID,))
        data = c.fetchall()
        conn.commit()
        return data
    elif CRUD == "U":
        _ID = row[0]
        _name = row[1]
        _active = row[2]
        _orderBy = row[3]
        c.execute("UPDATE tblServerRole SET  name = ?,  active = ?, orderBy = ?  where ID = ?" ,( _name, _active, _orderBy, _ID))
        conn.commit()
    elif CRUD == "D":
        _ID = row[0]
        c.execute("Delete From tblServerRole where ID = ?", (_ID,))
        conn.commit()
    else:
        c.execute("SELECT * FROM tblServerRole")
        data = c.fetchall()
        conn.commit()
        return data
    c.close()
    conn.close()

def CRUD_tblServersIP(row,CRUD):
    conn = sqlite3.connect(database)
    #conn.text_factory = lambda x: unicode(x, 'utf-8', 'ignore')
    c = conn.cursor()
    unix = time.time()
    if CRUD == "C":
        _serverName = row[0] 
        _ipAddress= row[1]
        _ports = row[2]
        _active = row[3]
        _pingTime = str(datetime.fromtimestamp(unix).strftime('%Y-%m-%d %H:%M:%S'))
        _serverroleid = row[4]
        c.execute("Insert INTO tblServersIP(serverName, ipAddress, ports, active, pingTime, serverroleid) VALUES (?, ?, ?,?,?,?)",(_serverName, _ipAddress, _ports, _active,_pingTime,_serverroleid))
        conn.commit()
        return c.lastrowid
    elif CRUD == "R":
        _ServerIP_ID = row[0]
        c.execute("SELECT * FROM tblServersIP where ServerIP_ID = ?", (_ServerIP_ID,))
        data = c.fetchall()
        conn.commit()
        return data
    elif CRUD == "U":
        _ServerIP_ID = row[0]
        _serverName = row[1]
        _ipAddress= row[2]
        _ports = row[3]
        _active = row[4]
        _pingTime = str(datetime.fromtimestamp(unix).strftime('%Y-%m-%d %H:%M:%S'))
        _serverroleid = row[5]
        c.execute("UPDATE tblServersIP SET  serverName = ?, ipAddress= ?, ports = ?, active = ?, pingTime = ?, serverroleid = ?  where ServerIP_ID = ?" ,( _serverName, _ipAddress, _ports, _active, _pingTime, _serverroleid,  _ServerIP_ID))
        conn.commit()
    elif CRUD == "D":
        _ServerIP_ID = row[0]
        c.execute("Delete From tblServersIP where ServerIP_ID = ?", (_ServerIP_ID,))
        conn.commit()
    else:
        c.execute("SELECT * FROM tblServersIP")
        data = c.fetchall()
        conn.commit()
        return data
    c.close()
    conn.close()
    


def CRUD_tblScenes(row,CRUD):
    conn = sqlite3.connect(database)
    #conn.text_factory = lambda x: unicode(x, 'utf-8', 'ignore')
    c = conn.cursor()
    unix = time.time()
    if CRUD == "C":
        _sceneName = row[0] 
        _active = row[1]
        _orderBY = row[2]
        _campaign_ID = row[3]
        c.execute("Insert INTO tblScenes(sceneName, active, orderBy, campaign_id) VALUES (?, ?, ?,?)",(_sceneName, _active, _orderBY,_campaign_ID))
        conn.commit()
        return c.lastrowid
    elif CRUD == "R":
        _Scene_ID = row[0]
        c.execute("SELECT * FROM tblScenes where Scene_ID = ?", (_Scene_ID,))
        data = c.fetchall()
        conn.commit()
        return data
    elif CRUD == "U":
        _Scene_ID = row[0]
        _sceneName = row[1]
        _active = row[2]
        _orderBY = row[3]
        _campaign_ID = row[4]
        c.execute("UPDATE tblScenes SET  sceneName = ?, active = ?, orderBY = ?, campaign_id = ? where scene_ID = ?" ,( _sceneName, _active, _orderBY,_campaign_ID, _Scene_ID))
        conn.commit()
    elif CRUD == "D":
        _Scene_ID = row[0]
        c.execute("Delete From tblScenes where Scene_ID = ?", (_Scene_ID,))
        conn.commit()
    else:
        c.execute("SELECT * FROM tblScenes")
        data = c.fetchall()
        conn.commit()
        return data
    c.close()
    conn.close()

def CRUD_tblScenePattern(row,CRUD):
    conn = sqlite3.connect(database)
    #conn.text_factory = lambda x: unicode(x, 'utf-8', 'ignore')
    c = conn.cursor()
    unix = time.time()
    if CRUD == "C":
        _scene_ID = row[0] 
        _ledTypeModel_ID = row[1]
        _color = row[2]
        _wait_ms = row[3]
        _iterations = row[4]
        _direction = row[5]
        _cdiff = row[6]
        _OrderBy = row[7]
        _OutPin = row[8]
        _brightness = row[9]
        c.execute("Insert INTO tblScenePattern(scene_ID, ledTypeModel_ID, color, wait_ms, iterations, direction, cdiff,OrderBy, OutPin, brightness) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",(_scene_ID, _ledTypeModel_ID, _color, _wait_ms, _iterations, _direction, _cdiff, _OrderBy, _OutPin, _brightness))
        conn.commit()
        return c.lastrowid
    elif CRUD == "R":
        _ScenePattern_ID = row[0]
        c.execute("SELECT * FROM tblScenePattern where ScenePattern_ID = ?", (_ScenePattern_ID,))
        data = c.fetchall()
        conn.commit()
        return data
    elif CRUD == "bySceneID":
        _Scene_ID = row[0]
        c.execute("SELECT * FROM tblScenePattern where Scene_ID = ? order by OrderBy", (_Scene_ID,))
        data = c.fetchall()
        conn.commit()
        return data
    elif CRUD == "U":
        _ScenePattern_ID = row[0]
        _Scene_ID = row[1]
        _ledTypeModel_ID = row[2]
        _color = row[3]
        _wait_ms = row[4]
        _iterations = row[5]
        _direction = row[6]
        _cdiff = row[7]
        _OrderBy = row[8]
        _OutPin = row[9]
        _brightness = row[10]
        c.execute("UPDATE tblScenePattern SET Scene_ID = ?, ledTypeModel_ID = ?, color = ?, wait_ms = ?, iterations = ?, direction = ?, cdiff = ?, OrderBy = ?, OutPin = ?, brightness = ? where ScenePattern_id = ?",(_Scene_ID,  _ledTypeModel_ID,  _color, _wait_ms, _iterations, _direction, _cdiff, _OrderBy, _OutPin, _brightness, _ScenePattern_ID))
        conn.commit()
    elif CRUD == "D":
        _ScenePattern_ID = row[0]
        c.execute("Delete From tblScenePattern where ScenePattern_ID = ?", (_ScenePattern_ID,))
        conn.commit()
    else:
        c.execute("SELECT * FROM tblScenePattern")
        data = c.fetchall()
        conn.commit()
        return data
    c.close()
    conn.close()

def CRUD_tblLEDTypeModel(row,CRUD):
    conn = sqlite3.connect(database)
    #conn.text_factory = lambda x: unicode(x, 'utf-8', 'ignore')
    c = conn.cursor()
    unix = time.time()
    if CRUD == "C":
        _modelName = row[0] 
        _ledJSON = row[1]
        c.execute("Insert INTO tblLEDTypeModel(modelName, ledJSON) VALUES (?, ?)",(_modelName, _ledJSON))
        conn.commit()
        return c.lastrowid
    elif CRUD == "R":
        _LEDTypeModel_ID = str(row)
        #print("LEDTypeModel_ID = " + _LEDTypeModel_ID)
        sql_query = f"SELECT * FROM tblLEDTypeModel WHERE LEDTypeModel_ID IN ({_LEDTypeModel_ID})"
        #c.execute("SELECT * FROM tblLEDTypeModel where LEDTypeModel_ID in ( ? )", (_LEDTypeModel_ID,))
        #print(sql_query)
        c.execute(sql_query)
        data = c.fetchall()
        conn.commit()
        return data
    elif CRUD == "U":
        _LEDTypeModel_ID = row[0] 
        _modelName = row[1]
        _ledJSON = row[2]
        c.execute("UPDATE tblLEDTypeModel SET modelName = ?, ledJSON = ? where LEDTypeModel_id = ?",(_modelName,  _ledJSON,  _LEDTypeModel_ID))
        conn.commit()
    elif CRUD == "D":
        _LEDTypeModel_ID = row[0]
        c.execute("Delete From tblLEDTypeModel where LEDTypeModel_ID = ?", (_LEDTypeModel_ID,))
        conn.commit()
    else:
        c.execute("SELECT * FROM tblLEDTypeModel")
        data = c.fetchall()
        conn.commit()
        return data
    c.close()
    conn.close()

def CRUD_tblMusicScene(row,CRUD):
    conn = sqlite3.connect(database)
    #conn.text_factory = lambda x: unicode(x, 'utf-8', 'ignore')
    c = conn.cursor()
    unix = time.time()
    if CRUD == "C":
        _scene_ID = row[0]
        _song_ID = row[1]
        _orderBy = row[2]
        _volume = row[3]
        _loops = row[4] if len(row) > 4 else 0   # optional: existing callers pass 4 fields
        c.execute("Insert INTO tblMusicScene(scene_ID, song_ID, orderBy,volume, loops) VALUES (?, ?, ?, ?, ?)",(_scene_ID, _song_ID, _orderBy, _volume, _loops))
        conn.commit()
        return c.lastrowid
    elif CRUD == "R":
        _MusicScene_ID = row[0]
        c.execute("SELECT * FROM tblMusicScene where MusicScene_ID = ?", (_MusicScene_ID,))
        data = c.fetchall()
        conn.commit()
        return data
    elif CRUD == "U":
        _MusicScene_ID = row[0] 
        _scene_ID = row[1]
        _song_ID = row[2]
        _orderBy = row[3]
        c.execute("UPDATE tblMusicScene SET scene_ID = ?, song_ID = ?,  orderBy = ? where MusicScene_id = ?",(_scene_ID,  _song_ID,  _orderBy, _MusicScene_ID))
        conn.commit()
    elif CRUD == "D":
        _MusicScene_ID = row[0]
        c.execute("Delete From tblMusicScene where MusicScene_ID = ?", (_MusicScene_ID,))
        conn.commit()
    else:
        c.execute("SELECT * FROM tblMusicScene")
        data = c.fetchall()
        conn.commit()
        return data
    c.close()
    conn.close()

def CRUD_tblPixel(row,CRUD):
    conn = sqlite3.connect(database)
    #conn.text_factory = lambda x: unicode(x, 'utf-8', 'ignore')
    c = conn.cursor()
    unix = time.time()
    if CRUD == "C":
        _pin = row[0] 
        _ledCount = row[1]
        c.execute("Insert INTO tblPixel(pin, ledCount) VALUES (?, ?)",(_pin, _ledCount))
        conn.commit()
        return c.lastrowid
    elif CRUD == "R":
        _pixel_ID = row[0]
        c.execute("SELECT * FROM tblPixel where pixel_ID = ?", (_pixel_ID,))
        data = c.fetchall()
        conn.commit()
        return data
    elif CRUD == "U":
        _pixel_ID = row[0] 
        _pin = row[1]
        _ledCount = row[2]
        c.execute("UPDATE tblPixel SET pin = ?, ledCount = ? where pixel_id = ?",(_pin,  _ledCount, _pixel_ID))
        conn.commit()
    elif CRUD == "D":
        pixel_ID = row[0]
        c.execute("Delete From tblPixel where pixel_ID = ?", (pixel_ID,))
        conn.commit()
    else:
        c.execute("SELECT * FROM tblPixel")
        data = c.fetchall()
        conn.commit()
        return data
    c.close()
    conn.close()

def CRUD_tblVideoScene(row,CRUD):
    conn = sqlite3.connect(database)
    #conn.text_factory = lambda x: unicode(x, 'utf-8', 'ignore')
    c = conn.cursor()
    unix = time.time()
    if CRUD == "C":
        _scene_ID = row[0] 
        _video_ID = row[1]
        _DisplayScreen_ID = row[2]
        _orderBy = row[3]
        _volume = row[4]
        _loops = row[5]
        c.execute("Insert INTO tblVideoScene(scene_ID, video_ID, DisplayScreen_ID, orderBy,volume, loops) VALUES (?, ?, ?,?, ?,?)",(_scene_ID, _video_ID,_DisplayScreen_ID, _orderBy, _volume, _loops))
        conn.commit()
        return c.lastrowid
    elif CRUD == "R":
        _VideoScene_ID = row[0]
        c.execute("SELECT * FROM tblVideoScene where VideoScene_ID = ?", (_VideoScene_ID,))
        data = c.fetchall()
        conn.commit()
        return data
    elif CRUD == "U":
        _VideoScene_ID = row[0] 
        _scene_ID = row[1]
        _video_ID = row[2]
        _DisplayScreen_ID = row[3]
        _orderBy = row[4]
        _volume = row[5]
        c.execute("UPDATE tblVideoScene SET scene_ID = ?, video_ID = ?, DisplayScreen_ID = ?, orderBy = ?, volume = ?, loops = ? where VideoScene_id = ?",(_scene_ID,  _video_ID, _DisplayScreen_ID, _orderBy, _volume, _loops, _VideoScene_ID))
        conn.commit()
    elif CRUD == "D":
        VideoScene_ID = row[0]
        c.execute("Delete From tblVideoScene where VideoScene_ID = ?", (VideoScene_ID,))
        conn.commit()
    else:
        c.execute("SELECT * FROM tblVideoScene")
        data = c.fetchall()
        conn.commit()
        return data
    c.close()
    conn.close()

def loadDefaults():
    conn = sqlite3.connect(database)
    conn.text_factory = lambda x: unicodedata(x, 'utf-8', 'ignore')
    c = conn.cursor()
    #c.execute("insert into tblMusicScene(scene_ID,song_ID,orderBy)values(1,6,1)")
    #c.execute("insert into tblMusicScene(scene_ID,song_ID,orderBy)values(1,3,2)")
    #c.execute("insert into tblScenePattern (scene_ID,ledTypeModel_ID,Color,wait_ms,interations ,direction) values (1,1,'[0,0,0]',10,100,1)")
    #c.execute("insert into tblScene (scenesName,orderby) values ('Sparkle',1)")
    #c.execute("insert into tblLEDTypeModel(modelName, ledJSON) values ('sparkle','{\"type\": \"sparkle\", \"color\": [0,0,0], \"wait_ms\": 8,\"cdiff\": [0,0,0],\"iterations\": 1000000}')")
    #c.execute("insert into tblPixel (pin,ledCount) values (26,86)")
    #c.execute("insert into tblVideoScene (scene_id,Video_ID,DisplayScreen_ID) values (1,1,1)")
    conn.commit()
    c.close()
    conn.close()

def get_SceneID(_scenePattern_ID):
    conn = sqlite3.connect(database)
    #conn.text_factory = lambda x: unicode(x, 'utf-8', 'ignore')
    c = conn.cursor()
    c.execute("SELECT scene_ID FROM tblScenePattern where scenePattern_ID = ?", (_scenePattern_ID,))
    data = c.fetchall()
    conn.commit()
    c.close()
    conn.close()
    return data

def get_VideoScene_BYSceneID(_scene_ID):
    conn = sqlite3.connect(database)
    #conn.text_factory = lambda x: unicode(x, 'utf-8', 'ignore')
    c = conn.cursor()
    c.execute("SELECT * FROM tblVideoScene where scene_ID = ?", (_scene_ID,))
    data = c.fetchall()
    c.execute("DELETE FROM tblLED")
    conn.commit()
    c.close()
    conn.close()
    return data

def get_MusicSceneSongs_BYSceneID(_scene_ID):
    conn = sqlite3.connect(database)
    #conn.text_factory = lambda x: unicode(x, 'utf-8', 'ignore')
    c = conn.cursor()
    c.execute("SELECT * FROM tblMusicScene where scene_ID = ?", (_scene_ID,))
    data = c.fetchall()
    c.execute("DELETE FROM tblLED")
    conn.commit()
    c.close()
    conn.close()
    return data

def get_LEDJSON():
    conn = sqlite3.connect(database)
    #conn.text_factory = lambda x: unicode(x, 'utf-8', 'ignore')
    c = conn.cursor()
    c.execute("SELECT ledJSON FROM tblLED")
    data = c.fetchall()
    c.execute("DELETE FROM tblLED")
    conn.commit()
    c.close()
    conn.close()
    # Latest row wins; empty table = lights off (see led_Run.get_LEDJSON).
    row = '{"patterns": [{"type": "solid", "color": [0, 0, 0]}]}'
    for r in data:
        row = r[0]
    return row

def insert_LEDJSON(json):
    conn = sqlite3.connect(database)
    conn.text_factory = lambda x: unicodedata(x, 'utf-8', 'ignore')
    c = conn.cursor()
    c.execute("INSERT INTO tblLED (ledJSON) VALUES (?)",[json])
    conn.commit()
    
# def insert_LEDJSON(json):
#     conn = sqlite3.connect(database)
#     conn.text_factory = lambda x: unicodedata(x, 'utf-8', 'ignore')
#     c = conn.cursor()
#     c.execute("INSERT INTO tblLED (ledJSON) VALUES (?)",[json])
#     conn.commit()

def update_video_data_entry(row):
    conn = sqlite3.connect(database)
    #conn.text_factory = lambda x: unicode(x, 'utf-8', 'ignore')
    c = conn.cursor()
    unix = time.time()
    _video_id = row[0]
    _playedDTTM = str(datetime.fromtimestamp(unix).strftime('%Y-%m-%d %H:%M:%S'))
    _pTimes = row[4]
    _pTimes = _pTimes + 1
    _active = row[5]
    _que = 0
    c.execute("UPDATE tblvideomedia SET pTimes = ?, playedDTTM = ?, active = ?, que = ? where video_ID = ?",(_pTimes, _playedDTTM, _active,  _que, _video_id))
    conn.commit()
    c.close()
    conn.close()
    
def update_data_entry(row):
    conn = sqlite3.connect(database)
    #conn.text_factory = lambda x: unicode(x, 'utf-8', 'ignore')
    c = conn.cursor()
    unix = time.time()
    _song_id = row[0]
    _playedDTTM = str(datetime.fromtimestamp(unix).strftime('%Y-%m-%d %H:%M:%S'))
    _pTimes = row[4]
    _pTimes = _pTimes + 1
    _active = row[5]
    _que = 0 if not appsettingGetKeepMusicPlaying() else row[6]
    c.execute("UPDATE tblMusic SET pTimes = ?, playedDTTM = ?, active = ?, que = ? where song_ID = ?",(_pTimes, _playedDTTM, _active,  _que, _song_id))
    conn.commit()
    c.close()
    conn.close()

def CRUD_tblHours(row,CRUD):
    conn = sqlite3.connect(database)
    #conn.text_factory = lambda x: unicode(x, 'utf-8', 'ignore')
    c = conn.cursor()
    unix = time.time()
    if CRUD == "C":
        _startDTTM = row[1] #str(datetime.fromtimestamp(unix).strftime('%Y-%m-%d %H:%M:%S'))
        _endDTTM = row[2]   #str(datetime.fromtimestamp(unix).strftime('%Y-%m-%d %H:%M:%S'))
        _gmt = row[3]
        _active = row[4]
        c.execute("Insert INTO tblHours(startDTTM, endDTTM, gmt, active) VALUES(?, ?, ?, ?)",(_startDTTM, _endDTTM, _gmt, _active))
        conn.commit()
    elif CRUD == "R":
        _hours_id = row(0)
        c.execute("SELECT hours_id, startDTTM, endDTTM, gmt, active FROM tblHours where hours_id = ?", (_hours_id))
        conn.commit()
    elif CRUD == "U":
        _hours_id = row[0]
        _startDTTM = row[1] #str(datetime.fromtimestamp(unix).strftime('%Y-%m-%d %H:%M:%S'))
        _endDTTM = row[2]   #str(datetime.fromtimestamp(unix).strftime('%Y-%m-%d %H:%M:%S'))
        _gmt = row[3]
        _active = row[4]
        c.execute("UPDATE tblHours SET startDTTM = ?, endDTTM = ?, gmt = ?, active = ? where hours_id = ?",(_startDTTM, _endDTTM, _gmt,  _active, _hours_id))
        conn.commit()
    elif CRUD == "D":
        _hours_id = row(0)
        c.execute("Delete From tblHours where hours_id = ?", (_hours_id))
        conn.commit()
    else:
        c.execute("SELECT hours_id, startDTTM, endDTTM, gmt, active FROM tblHours")
        conn.commit()
    c.close()
    conn.close()

def CRUD_tblGlobalVars(row,CRUD):
    conn = sqlite3.connect(database)
    #conn.text_factory = lambda x: unicode(x, 'utf-8', 'ignore')
    c = conn.cursor()
    unix = time.time()
    if CRUD == "C":
        _varName = row[1] 
        _varType = row[2]
        _varValue = row[3]
        _active = row[4]
        c.execute("Insert INTO tblGlobalVar(varName, varType, varValue, active)) VALUES(?, ?, ?, ?)",(_varName, _varType, _varValue, _active))
        conn.commit()
    elif CRUD == "R":
        _globalVar_id = row(0)
        c.execute("SELECT globalVar_id, varName, varType, varValue, active FROM tblGlobalVar where globalVar_id = ?", (_globalVar_id))
        conn.commit()
    elif CRUD == "U":
        _varName = row[1] 
        _varType = row[2]
        _varValue = row[3]
        _active = row[4]
        c.execute("UPDATE tblGlobalVar SET varName = ?, varType = ?, varValue = ?, active = ? where _globalVar_id = ?",(_varName, _varType, _varValue,  _active, _globalVar_id))
        conn.commit()
    elif CRUD == "D":
        globalVar_id = row(0)
        c.execute("Delete From tblGlobalVar where _globalVar_id = ?", (globalVar_id))
        conn.commit()
    else:
        c.execute("SELECT globalVar_id, varName, varType, varValue, active FROM tblGlobalVar")
        conn.commit()
    c.close()
    conn.close()

def select_play():
    blnEnd = 0
    while (blnEnd == 0):
        conn = sqlite3.connect(database)
        #conn.text_factory = lambda x: unicode(x, 'utf-8', 'ignore')
        c = conn.cursor()
        c.execute("SELECT song_ID, (path || song),path,song,pTimes,active,que FROM tblMusic where que = 1") #ORDER BY RANDOM() ")
        data = c.fetchall()
        c.close()
        conn.close()
        for row in data:
           #print(row[3])
           play_mp3(row[1])
           update_data_entry(row)
        blnEnd = 1 

def add_songID_Queue(_song_ID):
    conn = sqlite3.connect(database)
    c = conn.cursor()
    c.execute("UPDATE tblMusic SET  que = 1 where song_id = ?",(_song_ID,))
    conn.commit()
    c.close()
    conn.close()


def update_play_queue(_fn):
    songCount = 0
    conn = sqlite3.connect(database)
    c = conn.cursor()
    c.execute("UPDATE tblMusic SET  que = 1 where path like '%" + _fn + "%' or song like '%" + _fn + "%'")
    conn.commit()
    data = c.execute("SELECT count(*) FROM tblMusic where que = 1")
    for row in data:
        songCount = row[0]
    c.close()
    conn.close()
    return songCount

def update_video_queue_selected(_selected):
    videoCount = 0
    conn = sqlite3.connect(database)
    #print(_selected)
    c = conn.cursor()
    if len(_selected) > 0:
        for i in _selected:
            c.execute("UPDATE tblvideomedia SET que = 1 where dnLoadStatus = 3 and video_ID = " + str(i))
            conn.commit()
    data = c.execute("SELECT count(*) FROM tblvideomedia where que = 1")
    for row in data:
        videoCount = row[0]
    c.close()
    conn.close()
    return videoCount

def update_play_queue_selected(_selected):
    songCount = 0
    conn = sqlite3.connect(database)
    #print(_selected)
    c = conn.cursor()
    if len(_selected) > 0:
        for i in _selected:
            c.execute("UPDATE tblMusic SET  que = 1 where dnLoadStatus = 3 and song_id = " + str(i))
            conn.commit()
    data = c.execute("SELECT count(*) FROM tblMusic where que = 1")
    for row in data:
        songCount = row[0]
    c.close()
    conn.close()
    return songCount

def select_play_queue():
    blnEnd = 0
    conn = sqlite3.connect(database)
    #conn.text_factory = lambda x: unicode(x, 'utf-8', 'ignore')
    c = conn.cursor()
    while (blnEnd == 0):
        c.execute("SELECT song_ID, (path || song),path,song,pTimes,active,que FROM tblMusic WHERE que <> 0 ORDER BY RANDOM(), ROWID ASC LIMIT 1")
        data = c.fetchall()
        if len(data) == 0:
            blnEnd = 1
        else:    
            for row in data:
               #print(row[3])
               play_mp3(row[1])
               update_data_entry(row)
    c.close()
    conn.close()

def select_play_threadQ():
    # Filter the scene join to the ACTIVE scene: with videoId dedup one media row
    # can be linked to many scenes, and the old unfiltered join returned one row
    # PER LINK — playback could pick another scene's volume/order at random.
    # LEFT JOIN keeps media queued outside any scene playable (volume falls back
    # to 100), and the (IS NULL) sort keeps in-scene ordering first.
    scene = appsettingGetCurrentScene()
    conn = sqlite3.connect(database)
    c = conn.cursor()
    c.execute("SELECT m.song_ID, (m.path || m.song),m.path,m.song,m.pTimes,m.active,m.que, COALESCE(ms.volume, 100), COALESCE(ms.loops, 0) "
              "FROM tblMusic m LEFT JOIN tblMusicScene ms ON m.song_ID = ms.song_ID AND ms.scene_ID = ? "
              "WHERE m.que <> 0 and m.dnLoadStatus = 3 "
              "ORDER BY (ms.orderBy IS NULL), ms.orderBy, RANDOM(), m.ROWID ASC LIMIT 1", (scene,))
    data = c.fetchall()
    c.close()
    conn.close()
    for row in data:
        #update_data_entry(row)
        return row
    return ""

def select_video_threadQ():
    # Same active-scene filter as select_play_threadQ (see comment there).
    scene = appsettingGetCurrentScene()
    conn = sqlite3.connect(database)
    c = conn.cursor()
    c.execute("SELECT vm.video_ID, (vm.path || vm.title),vm.path,vm.title,vm.pTimes,vm.active,vm.que, "
              "COALESCE(vs.displayScreen_ID, 0), COALESCE(vs.volume, 100), COALESCE(vs.loops, 0) "
              "FROM tblVideoMedia vm LEFT JOIN tblVideoScene vs ON vm.video_ID = vs.video_ID AND vs.scene_ID = ? "
              "WHERE vm.que <> 0 and vm.dnLoadStatus = 3 "
              "ORDER BY (vs.orderBy IS NULL), vs.orderBy, RANDOM(), vm.ROWID ASC LIMIT 1;", (scene,))
    data = c.fetchall()
    #print(f"Video {data}")
    c.close()
    conn.close()
    for row in data:
        #update_data_entry(row)
        return row
    return ""

def queue_off():
    conn = sqlite3.connect(database)
    c = conn.cursor()
    c.execute("UPDATE tblMusic SET  que = 0 where que = 1")
    conn.commit()
    c.execute("UPDATE tblVideoMedia SET  que = 0 where que = 1")
    conn.commit()
    c.close()
    conn.close()

def queue_kill():
    conn = sqlite3.connect(database)
    c = conn.cursor()
    keep_music = appsettingGetKeepMusicPlaying()
    # Video always stops here (mpv is killed below); music only when the
    # keep-music toggle is off — mirror that in the now-playing settings.
    c.execute("UPDATE tblAppSettings SET value = '0' WHERE name = 'currentvideo'")
    if not keep_music:
        c.execute("UPDATE tblAppSettings SET value = '0' WHERE name = 'currentsong'")
        c.execute("UPDATE tblMusic SET  que = 0 where que = 1")
        conn.commit()
        c.execute("UPDATE tblVideoMedia SET  que = 0 where que = 1")
        conn.commit()
    conn.commit()
    # Taper the music to silence before its kill so the cut isn't audible
    # mid-waveform (locally and on the relay stream alike).
    if not keep_music:
        mpv_ipc.music_fade_out()
    if os.name == "nt":
       _nt_kill_by_cmdline("mpvsocket-video")
       if not keep_music:
           _nt_kill_by_cmdline("mpvsocket-music")
    else:
       # Music and video are now SEPARATE mpv instances — kills target the
       # instance by its IPC socket name on the command line, never the bare
       # process name (a plain `pkill mpv` would take both players down).
       if not keep_music:
           os.system("pkill mpg123")   # legacy player, in case one is still up
           os.system("pkill -f mpvsocket-music")
       os.system("pkill -f mpvsocket-video")
    c.close()
    conn.close()


def _nt_kill_by_cmdline(substr):
    """Windows `pkill -f` equivalent: taskkill can only match by image name,
    which can't tell the two mpv instances apart — psutil matches the IPC
    socket name on the command line, exactly like pkill -f does on Linux."""
    try:
        import psutil
        for proc in psutil.process_iter(['cmdline']):
            try:
                if any(substr in arg for arg in (proc.info['cmdline'] or [])):
                    proc.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
    except Exception:
        pass


def queue_next():
    # Skips and restarts taper out instead of cutting — see mpv_ipc.
    mpv_ipc.music_fade_out()
    if os.name == "nt":
       _nt_kill_by_cmdline("mpvsocket-music")
    else:
       os.system("pkill mpg123")   # legacy player, in case one is still up
       os.system("pkill -f mpvsocket-music")
def queueVideo_next():
    if os.name == "nt":
       # was `taskkill /im cmdmp3win.exe` — which killed the AUDIO player
       _nt_kill_by_cmdline("mpvsocket-video")
    else:
       os.system("pkill -f mpvsocket-video")

def select_data_all():
    conn = sqlite3.connect(database)
    #conn.text_factory = lambda x: unicode(x, 'utf-8', 'ignore')
    c = conn.cursor()
    c.execute("SELECT * FROM tblMusic")
    data = c.fetchall()
    for row in data:
       print(row[0], row[1],row[2],row[3])
    c.close()
    conn.close()
    
def delete_all(_tableName):
    conn = sqlite3.connect(database)
    #conn.text_factory = lambda x: unicode(x, 'utf-8', 'ignore')
    c = conn.cursor()
    c.execute("DELETE FROM " + _tableName)
    conn.commit()
    c.close()
    conn.close()

def delete_songs(_selected):
    conn = sqlite3.connect(database)
    c = conn.cursor()
    for i in _selected:
        c.execute("SELECT (path || song) FROM tblMusic where song_id = " + str(i))
        data = c.fetchall()
        for row in data:
            os.remove(row[0])
    for i in _selected:
        c.execute("Delete from tblMusic where song_id = " + str(i))
        conn.commit()
    c.close()
    conn.close()

def addSongToDB(fi):
    conn = sqlite3.connect(database)
    c = conn.cursor()
    #conn.text_factory = lambda x: unicode(x, 'utf-8', 'ignore')
    _pTimes = 0
    _playedDTTM = ""
    _active = 1
    _genre = 0
    _que = 1
    _path, _song = os.path.split(fi)
    if os.name == 'nt':
        _path = _path + "\\"
        _path.replace("\\","\\\\",0)
    else:
        _path = _path + "/"
    try:
        c.execute("INSERT INTO tblMusic(path, song, pTimes, playedDTTM, active, genre, que) VALUES(?, ?, ?, ?, ?, ?, ?)",(_path, _song, _pTimes, _playedDTTM, _active, _genre, _que))
        conn.commit()
    except Exception as err:
        #logger.error(err)
        pass
    c.close()
    conn.close()

    
def find_store_files():
    files = []
    fileslocal = []
    start_dir = ""
    if os.name == 'nt':
        start_local  = os.path.dirname(os.path.realpath(__file__))
    else:
        start_dir  = "/media"
        start_local  = os.path.dirname(os.path.realpath(__file__))
    
    pattern   = "*.mp3"
    
    if os.name != 'nt':
        for dir,_,_ in os.walk(start_dir):
            files.extend(glob(os.path.join(dir,pattern)))

    for dir,_,_ in os.walk(start_local):
        fileslocal.extend(glob(os.path.join(dir,pattern)))

    conn = sqlite3.connect(database)
    c = conn.cursor()
    #conn.text_factory = lambda x: unicode(x, 'utf-8', 'ignore')
    _pTimes = 0
    _playedDTTM = ""
    _active = 1
    _genre = 0
    _que = 0
    if len(files) > 0:
        for file in files:
            _path, _song = os.path.split(file)
            if os.name == 'nt':
                _path = _path + "\\"
                _path.replace("\\","\\\\",0)
            else:
                _path = _path + "/"
            try:
                c.execute("INSERT INTO tblMusic(path, song, pTimes, playedDTTM, active, genre, que) VALUES(?, ?, ?, ?, ?, ?, ?)",(_path, _song, _pTimes, _playedDTTM, _active, _genre, _que))
                conn.commit()
            except Exception as err:
                #logger.error(err)
                pass
    else:
        for file in fileslocal:
            _path, _song = os.path.split(file)
            if os.name == 'nt':
                _path = _path + "\\"
                _path.replace("\\","\\\\",0)
            else:
                _path = _path + "/"
            try:
                c.execute("INSERT INTO tblMusic(path, song, pTimes, playedDTTM, active, genre, que) VALUES(?, ?, ?, ?, ?, ?, ?)",(_path, _song, _pTimes, _playedDTTM, _active, _genre, _que))
                conn.commit()
            except Exception as err:
                #logger.error(err)
                pass

    c.close()
    conn.close()
    

def play_mp3(fi):
   if os.name == "nt":
      # mpv is already the required player on Windows — no bundled ffplay.exe.
      # No IPC socket: this is fire-and-wait (chimes / legacy scene loops).
      # CREATE_NO_WINDOW: without it each spawn pops a console window.
      # --force-window=no: Windows mpv builds default force-window ON, which
      # opens a player window for audio even with --no-video.
      subprocess.Popen(['mpv', fi, '--no-terminal', '--no-video',
                        '--force-window=no'],
                       creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)).wait()
   else:
      subprocess.Popen(['mpg123', '-q', fi]).wait()

def drop_table(_tableName):
    conn = sqlite3.connect(database)
    #conn.text_factory = lambda x: unicode(x, 'utf-8', 'ignore')
    c = conn.cursor()
    c.execute("DROP TABLE IF EXISTS " + _tableName)
    conn.commit()
    c.close()
    conn.close()
    
def get_table():
    conn = sqlite3.connect(database)
    #conn.text_factory = lambda x: unicode(x, 'utf-8', 'ignore')
    c = conn.cursor()
    c.execute("SELECT name FROM sqlite_master WHERE type='table'")
    data = c.fetchall()
    for row in data:
       print(row)
    c.close()
    conn.close()
    
def select_data_stats():#a):
    conn = sqlite3.connect(database)
    c = conn.cursor()
    # c.execute("SELECT 'Songs Stored' as T, Count(*) as C FROM tblMusic "
            #   + "UNION SELECT 'Songs Queued' as T, Count(*) as C FROM tblMusic where que <> 0 "
             # + "UNION SELECT 'Total Songs Played' as T, SUM(pTimes) as C FROM tblMusic "
             # + "UNION SELECT 'Song Current' as T, song as c FROM tblMusic where song_id = " + str(a[2]) + " "
             # + "UNION SELECT 'Song Last' as T, song as c FROM tblMusic where song_id = " + str(a[3]) + " "
             # + "UNION SELECT 'Song Volume' as T, " + str(a[1]) + " as c"
            #  )
    # Third column: total queued PLAY seconds — metadata duration × the active
    # scene's loop count (--loop-file=N repeats N times, so N+1 plays; same
    # active-scene join rules as select_play_threadQ, out-of-scene rows fall
    # back to 1 play). Duration lives only in tblMediaMetadata, so queued rows
    # whose metadata hasn't been extracted yet contribute 0 — the total is a
    # floor until the queue catches up. ORDER BY T pins song before video
    # (base.html / site.js read these rows by index).
    scene = appsettingGetCurrentScene()
    c.execute(
              "SELECT 'songQCnt' as T, Count(*) as C, "
              + "IFNULL(SUM(md.duration * (COALESCE(ms.loops, 0) + 1)),0) as D "
              + "FROM tblMusic m "
              + "LEFT JOIN tblMusicScene ms ON ms.song_ID = m.song_ID AND ms.scene_ID = ? "
              + "LEFT JOIN tblMediaMetadata md ON md.media_type='music' AND md.media_id=m.song_id "
              + "WHERE m.que <> 0 "
              + "UNION SELECT 'videoQCnt' as T, Count(*) as C, "
              + "IFNULL(SUM(md.duration * (COALESCE(vs.loops, 0) + 1)),0) as D "
              + "FROM tblvideoMedia v "
              + "LEFT JOIN tblVideoScene vs ON vs.video_ID = v.video_id AND vs.scene_ID = ? "
              + "LEFT JOIN tblMediaMetadata md ON md.media_type='video' AND md.media_id=v.video_id "
              + "WHERE v.que <> 0 "
              + "ORDER BY T", (scene, scene)
             )
    data = c.fetchall()
    c.close()
    conn.close()
    #print(data)
    return data

def select_data_allsongs():
    conn = sqlite3.connect(database)
    c = conn.cursor()
    c.execute("SELECT song_id, (path || song) FROM tblMusic ORDER BY path, song")
    data = c.fetchall()
    c.close()
    conn.close()
    return data


#drop_table('tblMusic')
#create_table()
#delete_all('tblMusic')
#find_store_files()
#queue_kill()
#update_play_queue('')
#select_play_queue()
#select_play()
#get_table()
#select_data_all()
#select_data_stats()
#select_data_allsongs()

 
