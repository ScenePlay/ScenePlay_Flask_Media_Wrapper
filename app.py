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
            
# Set up the SIGCHLD signal handler
signal.signal(signal.SIGCHLD, reap_child)


app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + databaseDir
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.secret_key = os.environ.get('SECRET_KEY', 'change-me-in-production')
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
    ["Empty2",int(arr[14]),"int"]
]

def startTheadPlayer():
    appsettings(apparray)
    appsettingAudioPlayFlagUpdate(0)
    appsettingVideoPlayFlagUpdate(0)
    appsettingYT_QuePlayFlagUpdate(0)
    data = select_data_stats()#arr)
    #\
    
    v = Process(target=threaderVideo)#, args=(num, arr))
    v.start()
    p = Process(target=threader, args=(num, arr))
    p.start()
    y = Process(target=YTQue_threader)
    y.start()
    appsettingAudioPlayFlagUpdate(1)
    appsettingVideoPlayFlagUpdate(1)
    appsettingYT_QuePlayFlagUpdate(1)

    time.sleep(3)
    appsettingAudioPlayFlagUpdatePID(999999)  # clear stale PID so threader starts fresh
    queue_next()

    # Start relay receiver and push current party + library to relay
    if appsettingGet('relay_enabled', '0') == '1':
        import relay_receiver
        relay_receiver.start(app)
        with app.app_context():
            import relay_broadcaster
            relay_broadcaster.push_all_characters()
            relay_broadcaster.push_library()
    
    
if arr[0] > 0:
    if __name__ == '__main__':
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