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
import multiprocessing
from multiprocessing import Value, Array
import os
import signal
import sys
import time



def reap_child(signum, frame):
    """Reap exited children so they never linger as zombies — and do NOTHING
    else. A pid is free for kernel REUSE the instant waitpid returns, so
    signaling reaped pids afterward can only ever hit an unrelated new
    process. The old version kept an ever-growing kill list and re-SIGKILLed
    it on every child exit: once pids started recycling, it murdered fresh
    mpv/ffmpeg spawns at random — audible as playback dying on scene
    switches and the relay feed stopping ('late-running killall')."""
    while True:
        try:
            pid, _status = os.waitpid(-1, os.WNOHANG)
            if pid == 0:
                break
        except ChildProcessError:
            break
            
# Set up the SIGCHLD signal handler. Windows has no SIGCHLD (and no zombie
# processes to reap) — the workers there run as threads, so skip it entirely.
if hasattr(signal, 'SIGCHLD'):
    signal.signal(signal.SIGCHLD, reap_child)


app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + databaseDir
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
# Writers wait out ordinary lock contention (background workers commit every
# few seconds) instead of failing at sqlite's 5s default. Note: does NOT cover
# stale-snapshot upgrades (SQLITE_BUSY_SNAPSHOT) — never hold an ORM read
# transaction across a slow network call and then write on it.
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {'connect_args': {'timeout': 15}}
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
# Absolute directory so programmatic upgrade() works no matter the cwd the
# app was launched from (startApp.sh, systemd, IDE...).
migrate.init_app(app, db,
                 directory=os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                        'migrations'))
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


@app.context_processor
def inject_relay_status():
    """Navbar 'Relay ON' badge: when the box is used purely as a media player,
    make an enabled (and possibly forgotten) relay visible at a glance.
    relay_stale   = enabled but the receiver hasn't synced in >90s (same
                    threshold as the relay health check).
    relay_failing = a push to the relay DROPPED within the last 2 minutes —
                    the relay is enabled but API hits are failing, which also
                    slows actions that push (scene switches wait on timeouts).
                    Surfaced here so the DM sees it during play, not later on
                    the admin page."""
    out = {'relay_on': False, 'relay_stale': False,
           'relay_failing': False, 'relay_fail_msg': ''}
    try:
        from sql import appsettingGet
        from datetime import datetime, timezone
        if appsettingGet('relay_enabled', '0') != '1':
            return out
        out['relay_on'] = True
        stale = True
        last = appsettingGet('relay_last_sync', '')
        if last and last != '—':
            try:
                ts = datetime.strptime(last, '%Y-%m-%d %H:%M:%S')
                age = (datetime.now(timezone.utc).replace(tzinfo=None) - ts).total_seconds()
                stale = age > 90
            except ValueError:
                pass
        out['relay_stale'] = stale
        drop = appsettingGet('relay_push_last_drop', '')
        if drop and '|' in drop:
            d_ts, _key, err = (drop.split('|', 2) + ['', ''])[:3]
            try:
                ts = datetime.strptime(d_ts, '%Y-%m-%d %H:%M:%S')
                age = (datetime.now(timezone.utc).replace(tzinfo=None) - ts).total_seconds()
                if age < 120:
                    out['relay_failing'] = True
                    out['relay_fail_msg'] = err
            except ValueError:
                pass
        return out
    except Exception:
        return out



@app.context_processor
def inject_remote_led_status():
    """Navbar red 'LED Remote FAILING' badge: an LED transfer to another
    ScenePlay box failed within the last 2 minutes. Each dead Remote stalls
    every scene switch by its 4 s push timeout, so the DM needs to see it
    during play — the badge links to the Servers page, where deactivating
    the dead row clears both the failure and the stall."""
    out = {'led_remote_failing': False, 'led_remote_msg': '',
           'wled_failing': False, 'wled_msg': ''}
    try:
        from sql import appsettingGet
        from datetime import datetime, timezone

        def _recent(setting):
            rec = appsettingGet(setting, '')
            if rec and '|' in rec:
                ts_s, ip_addr, err = (rec.split('|', 2) + ['', ''])[:3]
                try:
                    ts = datetime.strptime(ts_s, '%Y-%m-%d %H:%M:%S')
                    age = (datetime.now(timezone.utc).replace(tzinfo=None) - ts).total_seconds()
                    if age < 120:
                        return f'{ip_addr}: {err}'
                except ValueError:
                    pass
            return ''

        msg = _recent('remote_send_last_fail')
        if msg:
            out['led_remote_failing'] = True
            out['led_remote_msg'] = msg
        msg = _recent('wled_send_last_fail')
        if msg:
            out['wled_failing'] = True
            out['wled_msg'] = msg
    except Exception:
        pass
    return out


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

# Startup schema sync. create_table()/db.create_all() only CREATE missing
# tables — they never alter existing ones. Column adds, indexes and seed fixes
# live in migrations/versions/ (see migrations/README) and are applied by
# flask_migrate.upgrade(), which records each revision in alembic_version.
# Unlike the ad-hoc ALTER blocks that used to live here, a failed migration
# RAISES: refusing to start beats running on a half-upgraded database.
with app.app_context():
    import models.tblTokenPositions  # noqa: F401
    import models.tblRollLog         # noqa: F401
    import models.mediaMetadata      # noqa: F401
    sqlite_tune()          # WAL mode — readers never block (see sql.sqlite_tune)
    create_table()
    db.create_all()
    from flask_migrate import upgrade as _fm_upgrade
    try:
        _fm_upgrade()
    except Exception as _e:
        raise RuntimeError(
            'Database schema migration failed — ScenePlay will not start on an '
            'inconsistent database. A pre-upgrade ScenePlay.db can be restored '
            'from backups/ if needed.') from _e

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
        # Crash forensics: a worker that dies takes its subsystem (music,
        # video, downloads...) silently with it — write the traceback where
        # it can be read after the fact, alongside the spawn/kill event log.
        def _guarded(*a):
            try:
                target(*a)
            except Exception:
                import traceback
                try:
                    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                           'player_debug.log'), 'a') as fh:
                        fh.write(f'\n=== WORKER {target.__name__} CRASHED (pid {os.getpid()}) ===\n')
                        traceback.print_exc(file=fh)
                except Exception:
                    pass
                raise
        _guarded.__name__ = f'guarded_{target.__name__}'
        if os.name == 'nt':
            import threading
            threading.Thread(target=_guarded, args=args, daemon=True,
                             name=f'worker-{target.__name__}').start()
        else:
            # Python 3.14 switched Linux's default start method from fork to
            # forkserver, which pickles the target — impossible for this local
            # closure, and a forkserver child wouldn't inherit the shared
            # Value/Array state anyway. Request fork explicitly.
            multiprocessing.get_context('fork').Process(
                target=_guarded, args=args).start()

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