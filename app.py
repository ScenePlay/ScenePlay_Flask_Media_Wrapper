from flask import Flask
from extensions import db, migrate, login_manager, bcrypt, databaseDir
from routes.main import main
from routes.scenePattern_table import sp
from routes.scenes_table import sn
from routes.Utilities import ut
from routes.ledtypemodel_table import ltm
from routes.campaign_table import cp
from routes.musicMedia_table import mu
from routes.genre_table import ge
from routes.serverIP_table import ip
from routes.serverRole_table import sr
from routes.musicScene_table import ms
from routes.videoMedia_table import vm
from routes.videoScene_table import vs
from routes.wledPattern_table import wl
from routes.dnLoadStatus_table import dls
from routes.ledconfig_table import lcf
from routes.cronSchedule_table import cs
from routes.auth import auth
from routes.ttrpg import ttrpg
from routes.monsters import monsters_bp
from routes.battlemap import battlemap_bp
from routes.reference import reference_bp
from routes.relay_admin import relay_admin_bp

from defaultData import *
from sql import *
from player import *
from mpvPlayer import *
from yt_que import *
from multiprocessing import Process, Value, Array
import os
import signal
import sys
import time



reaped_processes = []
def reap_child(signum, frame):
    while True:
        try:
            pid, status = os.waitpid(-1, os.WNOHANG)
            if pid == 0:
                break
            #print(f"Reaped child process {pid} with exit status {status}")
            reaped_processes.append(pid)
        except ChildProcessError:
            break
    for pid in reaped_processes:
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass
            
# Set up the SIGCHLD signal handler. Windows has no SIGCHLD (and no zombie
# processes to reap) — the workers there run as threads, so skip it entirely.
if hasattr(signal, 'SIGCHLD'):
    signal.signal(signal.SIGCHLD, reap_child)


app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + databaseDir
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['TEMPLATES_AUTO_RELOAD'] = True
def _load_or_create_secret_key():
    """SECRET_KEY env var wins; otherwise generate a random key once and persist
    it to the instance dir. Replaces the old 'change-me-in-production' fallback —
    zero-config and no shared default, and sessions survive restarts."""
    env_key = os.environ.get('SECRET_KEY')
    if env_key:
        return env_key
    key_path = os.path.join(os.path.dirname(os.path.realpath(__file__)),
                            'instance', 'secret_key')
    try:
        with open(key_path) as f:
            key = f.read().strip()
            if key:
                return key
    except OSError:
        pass
    import secrets as _secrets
    key = _secrets.token_hex(32)
    try:
        os.makedirs(os.path.dirname(key_path), exist_ok=True)
        with open(key_path, 'w') as f:
            f.write(key)
        os.chmod(key_path, 0o600)
    except OSError as e:
        print('Could not persist secret key (sessions reset each restart):', e)
    return key


app.secret_key = _load_or_create_secret_key()


@app.template_global()
def static_v(filename):
    """url_for('static', ...) with the file's mtime as a cache-busting query
    param — replaces the manual ?v=NN bump ritual, so LAN players never run a
    stale sfx.js/dice.js after an edit."""
    from flask import url_for
    path = os.path.join(app.root_path, 'static', filename)
    try:
        v = int(os.stat(path).st_mtime)
    except OSError:
        v = 0
    return url_for('static', filename=filename, v=v)
db.init_app(app)
migrate.init_app(app, db)
bcrypt.init_app(app)
login_manager.init_app(app)
login_manager.login_view = 'auth.login'

@login_manager.user_loader
def load_user(user_id):
    from models.user import tblUsers
    return db.session.get(tblUsers, int(user_id))

import json as _json
@app.template_filter('from_json')
def from_json_filter(s):
    try:
        return _json.loads(s or '[]')
    except Exception:
        return []

@app.context_processor
def inject_keep_music():
    from sql import appsettingGetKeepMusicPlaying
    return {'keep_music': appsettingGetKeepMusicPlaying()}



app.register_blueprint(main)
app.register_blueprint(sp)
app.register_blueprint(sn)
app.register_blueprint(ut)
app.register_blueprint(ltm)
app.register_blueprint(cp)
app.register_blueprint(mu)
app.register_blueprint(ge)
app.register_blueprint(ip)
app.register_blueprint(sr)
app.register_blueprint(ms)
app.register_blueprint(vm)
app.register_blueprint(vs)
app.register_blueprint(wl)
app.register_blueprint(dls)
app.register_blueprint(lcf)
app.register_blueprint(cs)
app.register_blueprint(auth)
app.register_blueprint(ttrpg)
app.register_blueprint(monsters_bp)
app.register_blueprint(battlemap_bp)
app.register_blueprint(reference_bp)
app.register_blueprint(relay_admin_bp)

# Ensure new tables exist (idempotent; does not drop existing tables)
with app.app_context():
    import models.tblTokenPositions  # noqa: F401
    import models.tblRollLog         # noqa: F401
    import models.mediaMetadata      # noqa: F401
    db.create_all()

    # Lightweight migration: add tblBattleMaps.sort_order to older DBs (create_all
    # never alters existing tables), then seed it from map_id so current maps keep
    # their order. Idempotent — skipped once the column exists.
    from sqlalchemy import text as _sa_text
    try:
        _cols = [r[1] for r in db.session.execute(_sa_text("PRAGMA table_info(tblBattleMaps)"))]
        if 'sort_order' not in _cols:
            db.session.execute(_sa_text(
                "ALTER TABLE tblBattleMaps ADD COLUMN sort_order INTEGER DEFAULT 0"))
            db.session.execute(_sa_text(
                "UPDATE tblBattleMaps SET sort_order = map_id"))
            db.session.commit()
    except Exception as _e:  # never block startup on a migration hiccup
        db.session.rollback()
        print('tblBattleMaps.sort_order migration skipped:', _e)

    # Lightweight migration: add relay_roll_id to the roll tables so relay rolls can
    # be de-duplicated by the relay's unique id (fixes fast/identical rolls being
    # dropped). Idempotent — skipped once the columns exist.
    for _tbl in ('tblRollLog', 'tblDiceRolls'):
        try:
            _cols = [r[1] for r in db.session.execute(_sa_text(f"PRAGMA table_info({_tbl})"))]
            if _cols and 'relay_roll_id' not in _cols:
                db.session.execute(_sa_text(
                    f"ALTER TABLE {_tbl} ADD COLUMN relay_roll_id INTEGER"))
                db.session.commit()
        except Exception as _e:
            db.session.rollback()
            print(f'{_tbl}.relay_roll_id migration skipped:', _e)

    # Lightweight migration: add tblTokenPositions.relay_seq — the last relay
    # write-sequence processed per token, used for clock-skew-free reconciliation
    # of relay token moves. Idempotent — skipped once the column exists.
    try:
        _cols = [r[1] for r in db.session.execute(_sa_text("PRAGMA table_info(tblTokenPositions)"))]
        if _cols and 'relay_seq' not in _cols:
            db.session.execute(_sa_text(
                "ALTER TABLE tblTokenPositions ADD COLUMN relay_seq INTEGER DEFAULT 0"))
            db.session.commit()
    except Exception as _e:
        db.session.rollback()
        print('tblTokenPositions.relay_seq migration skipped:', _e)

    # Lightweight migration: add tblCharacters.subclass — the archetype picked
    # from the synced subclasses library (Champion, Evoker…); drives subclass
    # features on the sheet. Idempotent — skipped once the column exists.
    try:
        _cols = [r[1] for r in db.session.execute(_sa_text("PRAGMA table_info(tblCharacters)"))]
        if _cols and 'subclass' not in _cols:
            db.session.execute(_sa_text(
                "ALTER TABLE tblCharacters ADD COLUMN subclass TEXT DEFAULT ''"))
            db.session.commit()
    except Exception as _e:
        db.session.rollback()
        print('tblCharacters.subclass migration skipped:', _e)

    # Lightweight migration: add tblServersIP.version — the app/firmware version a
    # discovered device reports via /api/server-info (ScenePlay) or /json/info
    # (WLED), shown next to its name in the server table. Idempotent.
    try:
        _cols = [r[1] for r in db.session.execute(_sa_text("PRAGMA table_info(tblServersIP)"))]
        if _cols and 'version' not in _cols:
            db.session.execute(_sa_text(
                "ALTER TABLE tblServersIP ADD COLUMN version TEXT"))
            db.session.commit()
    except Exception as _e:
        db.session.rollback()
        print('tblServersIP.version migration skipped:', _e)

    # Lightweight migration: video-id identity + metadata-queue columns on the two
    # media tables (create_all never alters existing tables). videoId = canonical
    # YouTube id (dedup key), displayName = human name from metadata, metaStatus =
    # metadata-queue lifecycle (lutStatus lexicon + 5=Unavailable), metaNextRetry =
    # backoff gate. Idempotent — each column added only if absent.
    for _mtbl in ('tblMusic', 'tblVideoMedia'):
        try:
            _cols = [r[1] for r in db.session.execute(_sa_text(f"PRAGMA table_info({_mtbl})"))]
            for _col, _decl in (('videoId', 'TEXT'), ('displayName', 'TEXT'),
                                ('metaStatus', 'INTEGER DEFAULT 0'), ('metaNextRetry', 'TEXT')):
                if _cols and _col not in _cols:
                    db.session.execute(_sa_text(f"ALTER TABLE {_mtbl} ADD COLUMN {_col} {_decl}"))
            db.session.commit()
        except Exception as _e:
            db.session.rollback()
            print(f'{_mtbl} metadata-column migration skipped:', _e)

    # Lightweight migration: retry backoff gate on the playlist queue (fresh DBs
    # get it in create_table()). Idempotent — added only if absent.
    try:
        _cols = [r[1] for r in db.session.execute(_sa_text("PRAGMA table_info(tblPlaylistQueue)"))]
        if _cols and 'next_retry' not in _cols:
            db.session.execute(_sa_text("ALTER TABLE tblPlaylistQueue ADD COLUMN next_retry TEXT"))
        db.session.commit()
    except Exception as _e:
        db.session.rollback()
        print('tblPlaylistQueue.next_retry migration skipped:', _e)

    # The partial UNIQUE index on videoId must exist AFTER the ALTERs above (a
    # fresh DB gets it in create_table(); an upgraded DB needs it here).
    for _mtbl, _idx in (('tblMusic', 'idx_tblMusic_videoId'),
                        ('tblVideoMedia', 'idx_tblVideoMedia_videoId')):
        try:
            db.session.execute(_sa_text(
                f"CREATE UNIQUE INDEX IF NOT EXISTS {_idx} ON {_mtbl}(videoId) WHERE videoId IS NOT NULL"))
            db.session.commit()
        except Exception as _e:
            db.session.rollback()
            print(f'{_idx} creation skipped:', _e)

    # Seed lutStatus row 5 "Unavailable" (permanent metadata failure). The JSON
    # loader only seeds when lutStatus is empty, so upgraded DBs need this insert.
    try:
        _has5 = db.session.execute(_sa_text("SELECT 1 FROM lutStatus WHERE status_ID = 5")).fetchone()
        if not _has5:
            db.session.execute(_sa_text(
                "INSERT INTO lutStatus(status_ID, status) VALUES (5, 'Unavailable')"))
            db.session.commit()
    except Exception as _e:
        db.session.rollback()
        print('lutStatus status-5 seed skipped:', _e)

# Ensure all upload directories exist
for _upload_dir in ('battlemaps', 'portraits', 'weapons', 'armor', 'monsters'):
    os.makedirs(os.path.join(app.root_path, 'static', 'uploads', _upload_dir), exist_ok=True)

num = Value('i', 1)
arr = Array('i', range(15))


#Running Vaiables
arr[0] = os.getpid()
arr[1] = 0 #volume 
arr[2] = 0  #current song
arr[3] = 0  #current video
arr[4] = 1  #StartSwitch
arr[5] = 1  #SongPID
arr[6] = 1  #VideoSwitch
arr[7] = 1  #VideoPID
arr[8] = 1  #YT_QueSwitch
arr[9] = 1  #YT_QuePID
arr[10] = 1  #WatchManage
arr[11] = 0  #Show Campaign DropDown
arr[12] = 0  #Current Campaign in Play
arr[13] = 0  #Show Scene to Filter
arr[14] = 0  #Empty


#find the current setting of WatchManage
create_table()
defaultData()
oldArr = CRUD_tblAppSettings([],"")
for a in oldArr:
    #print(a)
    if a[1] == "WatchManage":
        arr[10] = int(a[2])
        break
    
apparray = [
    ["ospid",int(arr[0]),"int"],
    ["volume",int(arr[1]), "int"],
    ["currentsong",str(arr[2]), "text"],
    ["currentvideo",str(arr[3]), "text"],
    ["playsongswitch",int(arr[4]),"int"],
    ["playsongPID",int(arr[5]),"int"],
    ["playvideoswitch",int(arr[6]),"int"],
    ["playvideoPID",int(arr[7]),"int"],
    ["yt_que_switch",int(arr[8]),"int"],
    ["yt_que_PID",int(arr[9]),"int"],
    ["WatchManage",int(arr[10]),"int"],
    ["ShowCampaign",int(arr[11]),"int"],
    ["CurrentCampaignPlaying",int(arr[12]),"int"],
    ["SceneFilter",int(arr[13]),"int"],
    ["Empty2",int(arr[14]),"int"],
    ["meta_que_switch",1,"int"],       # metadata worker gate (independent of arr)
    ["playlist_que_switch",1,"int"],   # playlist expansion worker gate
    ["CurrentScene",0,"int"]           # active scene for per-scene playback params
]

def startTheadPlayer():
    appsettings(apparray)
    appsettingAudioPlayFlagUpdate(0)
    appsettingVideoPlayFlagUpdate(0)
    appsettingYT_QuePlayFlagUpdate(0)
    data = select_data_stats()#arr)
    #\
    
    # All six workers are IO-bound sqlite pollers. On Linux they run as
    # detached Processes (unchanged). On Windows they run as daemon THREADS:
    # multiprocessing there uses spawn, which would re-import app.py's
    # module-level side effects (db.create_all, seeding, worker autostart)
    # into every child and lose the shared Value/Array state.
    def start_worker(target, args=()):
        if os.name == 'nt':
            import threading
            threading.Thread(target=target, args=args, daemon=True,
                             name=f'worker-{target.__name__}').start()
        else:
            Process(target=target, args=args).start()

    start_worker(threaderVideo)
    start_worker(threader, (num, arr))
    start_worker(YTQue_threader)
    # Metadata + playlist workers: independent pollers mirroring the download worker
    # (2s poll, appsetting-switch gated). Started here in startTheadPlayer (never in
    # a forkserver child) alongside the others.
    from meta_que import MetaQue_threader
    from playlist_que import PlaylistQue_threader
    recover_stuck_processing()   # re-queue jobs a crash left stranded at 'Processing'
    start_worker(MetaQue_threader)
    start_worker(PlaylistQue_threader)
    # Nightly backup scheduler — no-op unless backup_auto is switched on
    # (Utilities page). Same detached-worker pattern as the queues above.
    from backup_restore import Backup_threader
    start_worker(Backup_threader)
    appsettingAudioPlayFlagUpdate(1)
    appsettingVideoPlayFlagUpdate(1)
    appsettingYT_QuePlayFlagUpdate(1)
    appsettingFlagUpdate('meta_que_switch', 1)      # process any metadata backlog on boot
    appsettingFlagUpdate('playlist_que_switch', 1)

    time.sleep(3)
    appsettingAudioPlayFlagUpdatePID(999999)  # clear stale PID so threader starts fresh
    # Same for the download queue: a stale yt_que_PID that collides with a
    # live process would make the worker wait on it and never start downloads.
    appsettingYT_QuePlayFlagUpdatePID(999999)
    queue_next()

    # Start relay receiver and push current party + library to relay
    if appsettingGet('relay_enabled', '0') == '1':
        import relay_receiver
        relay_receiver.start(app)
        with app.app_context():
            import relay_broadcaster
            relay_broadcaster.push_all_characters()
            relay_broadcaster.push_session_users()
            relay_broadcaster.push_library()
    
    
def _another_instance_running(port=8086):
    """True when the app already runs elsewhere (dev-server F5 while the
    waitress instance is up). Starting anyway would add a second set of queue
    workers racing for the same DB rows — and the loser can't even serve."""
    import socket
    probe = socket.socket()
    # Linux: without SO_REUSEADDR a fresh restart false-positives on the old
    # socket's TIME_WAIT. Windows must NOT set it (it lets bind hijack a LIVE
    # listener, defeating the check); its bind ignores TIME_WAIT anyway.
    if os.name != 'nt':
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        probe.bind(('0.0.0.0', port))
        return False
    except OSError:
        return True
    finally:
        probe.close()


if arr[0] > 0:
    if __name__ == '__main__':
        if _another_instance_running():
            print('*** ScenePlay is already running (port 8086 in use) — '
                  'not starting a second instance. ***')
            sys.exit(1)
        startTheadPlayer()
    
    
if __name__ == '__main__':
    app.config['SESSION_TYPE'] = 'filesystem'
    noWaitress = sys.argv[1]
    
    if noWaitress == "-flask":
        app.run( 
            threaded=True,
            #debug=True,
            host="0.0.0.0",
            port=int("8086")
            )
    else:
        pass