from flask import Flask 
from extensions import *
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

from defaultData import *
from sql import *
from player import *
from mpvPlayer import *
from yt_que import *
from multiprocessing import Process, Value, Array
import os
import signal
import sys



reaped_processes = []
def reap_child(signum, frame):
    while True:
        try:
            pid, status = os.waitpid(-1, os.WNOHANG)
            if pid == 0:
                break
            print(f"Reaped child process {pid} with exit status {status}")
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
db.init_app(app)
migrate.init_app(app, db)

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
    
    
if arr[0] > 0:
    startTheadPlayer()
    
    
if __name__ == '__main__':
    app.secret_key = 'super secret key'

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