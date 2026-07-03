from flask import Blueprint, render_template,redirect,url_for,  request, abort, jsonify, json
from extensions import *

from sql import *
import alsaaudio
from multiprocessing import Process, Value, Array
import time
from ledPlayer import *
from sys import platform
import platform
from remotes import *
from pathlib import Path
from wLed.wledCommand import *
from routes.wledPattern_table import getWledPatternBySceneID
from flask import send_from_directory     
import re
import os

main = Blueprint('main', __name__)
#db.create_all()
num = Value('i', 0)
arr = Array('i', range(10))

arr[0] = os.getpid()
arr[1] = 0 #volume 
arr[2] = 0  #current song
arr[3] = 0  #previous song


@main.route('/favicon.ico',methods=['GET'])
def favicon():
    return send_from_directory(os.path.join('static/image'), 'favicon.ico', mimetype='image/vnd.microsoft.icon')

@main.route('/', methods=['GET', 'POST'])
def home():
    create_table()
    data = select_data_stats()#arr)
    volume = currentvolume()
    scenes = get_Scenes()
    campaigns = CRUD_tblCampaigns([], "Selected")
    campaignRow = appsettingGetCampaignSelected()
    try:
        campaignSelectedInt = int(campaignRow[0][0])
    except (IndexError, TypeError, ValueError):
        campaignSelectedInt = 0
    #print(campaignSelectedInt)
    # if request.method == 'POST':
    #     if request.form['submit'] == 'Next Song':
    #         PlayerBl = True
    #         queue_next()
    #         time.sleep(1)
    #         return  redirect(url_for('main.home'))
    return render_template('home.html',items=data, Scenes=scenes,volume=volume,Campaigns=campaigns, campaignSelected=campaignSelectedInt)

@main.after_request
def add_headers(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
    return response

@main.route("/set_volume", methods=["POST"])
def set_volume():
    json_data = json.loads(json.dumps(request.get_json()))
    new_volume = int(json_data["volume"])
    setvolume(new_volume)
    return "Volume set successfully!"

@main.route("/api/songandvideocount", methods=["GET"])
def songandvideocount():
    data = select_data_stats()#arr)
    dataDict = []
    for item in data:
        dataDict.append({item[0]: item[1]})
    #print(dataDict)
    return jsonify(dataDict)


def is_raspberry_pi() -> bool:
    CPUINFO_PATH = Path("/proc/cpuinfo")
    if not CPUINFO_PATH.exists():
        return False
    with open(CPUINFO_PATH) as file:
        content = file.read()
        if 'Raspberry Pi 5' in content:
            #print('Raspberry Pi 5 LED not supported')
            return False
    return platform.machine() in('armv7l', 'armv6l', 'aarch64')

@main.route('/api/server-info', methods=['GET'])
def server_info():
    """Fingerprint endpoint used for LAN discovery — an answering box IS a
    ScenePlay server. The network scanner (discovery.py) hits this on every
    host with the ScenePlay port open and records the ones that respond with
    app == 'ScenePlay'. Intentionally unauthenticated and read-only: it exposes
    only hostname/version/OS/core-count/capabilities so strangers on the LAN can
    identify it. Nothing here is sensitive and nothing here mutates state."""
    import socket as _socket
    from version import __version__

    # A friendly name if the operator set one, else the machine hostname.
    name = appsettingGet('server_name', None) or _socket.gethostname()

    # capabilities let a discovering box auto-classify this one:
    #   led   -> drives a physical LED strip (active tblLEDConfig row)
    #   relay -> local->relay sync is enabled here
    try:
        from models.ledConfig import tblledconfig
        has_led = db.session.query(tblledconfig.ledConfig_ID).filter(
            tblledconfig.active == 1).first() is not None
    except Exception:
        has_led = False

    return jsonify({
        'app':          'ScenePlay',
        'server_name':  name,
        'version':      __version__,
        'os':           platform.platform(),
        'machine':      platform.machine(),
        'cores':        os.cpu_count() or 1,
        'capabilities': {
            'led':   has_led,
            'relay': appsettingGet('relay_enabled', '0') == '1',
        },
    })


@main.route('/api/ChromeExtensionAddVideo', methods=['POST'])
def ChromeExtensionAddVideo():
    data = request.get_json()
    url = data['url']
    flname = data['flname']
    flname = sanitize_filename(flname)
    mediaType = data['mediaType']
    scene_ID = data['scene_ID']
    addMediaToYT_que(url,flname, mediaType, scene_ID)
    return jsonify('Success')#jsonf'Success'

def sanitize_filename(filename):
    return re.sub('[^A-Za-z0-9._-]', '_', filename)
def addMediaToYT_que(url,flname,mediaType, scene_ID):
            title = flname + '.' + mediaType
            filePath = ''
            if scene_ID == '':
                scene_ID = 0
            if mediaType == "mp3":
                filePath = str(Path.home()) + "/Music/SP/"
                row = [filePath, title, 0, '', 1, 0, 0, url, 1]
                newrow_ID = CRUD_tblMusic(row, "C")
                if  int(scene_ID) > 0:
                    scene_row = [int(scene_ID), int(newrow_ID), 1, 100]
                    CRUD_tblMusicScene(scene_row, "C")
            else:
                filePath = str(Path.home()) + "/Videos/SP/"
                row = [filePath, title, 0, '', 1, 0, 0, url, 1]
                newrow_ID = CRUD_tblvideomedia(row, "C")
                if int(scene_ID) > 0:
                    scene_row = [int(scene_ID), int(newrow_ID),0, 1, 100,0]
                    CRUD_tblVideoScene(scene_row, "C")
            appsettingYT_QuePlayFlagUpdate(1)         

@main.route('/updateWLEDSupport', methods=['POST'])
def updateWLEDSupport():
    try:
        data = json.dumps(request.get_json())
        #print(data)
        if "ServerIP_ID" not in data:
            abort(400)
        ServerIP_ID = json.loads(data)["ServerIP_ID"]
        addEffectsPallettes(ServerIP_ID)
    except Exception as e:
        print(e)
    return f"'Update Effects and Pallettes using ServerIP_ID': {ServerIP_ID}"
        
@main.route('/activatescenes/', methods=['GET', 'POST'])
def activatescene():
    id = request.args.get('id')
    scnID = []
    scnID.append(id)
    scnPat = CRUD_tblScenePattern(scnID,"bySceneID")
    #print(scnPat)
    ledMdl = None
    _scene_ID = []
    _ledType_ID = []
    if len(scnPat) > 0:
        id_list = [str(item[2]) for item in scnPat]
        ledTypestrIDS = ",".join(id_list)
        ledMdl = CRUD_tblLEDTypeModel(ledTypestrIDS ,"R")
        # #get all songs associated with scene
    rows = get_MusicSceneSongs_BYSceneID(id)
    rowsVideo = get_VideoScene_BYSceneID(id)
    
    queue_kill()
    selected = []
    if len(rows) > 0:
        for row in rows:
            #print(row[2])
            selected.append(row[2])
        PlayerBl = True    
        update_play_queue_selected(selected)
    
    selectedVideo = []
    if len(rowsVideo) > 0:
        for row in rowsVideo:
            #print(row[2])
            selectedVideo.append(row[2])
        PlayerVideoBl = True    
        update_video_queue_selected(selectedVideo)
    #build json for led
    
    rows = CRUD_tblMusicScene(id,"R") 
    i=0
    
    data = getWledPatternBySceneID(id)
    if data is not None:
        for row in data:
            #print(row.effect)
            setWledEffect(row.effect,row.pallette,row.color1, row.color2, row.color3, row.speed, row.brightness, row.server_ID)
    if len(data) == 0:
        wled_Off()
        
    if ledMdl is not None and len(ledMdl) > 0:
            ledPattern = prepJsonRemote(ledMdl, scnPat)
            ledPattern = ledPattern.replace("\"",'"')
            ledPattern = json.dumps(str(ledPattern))
            ledPattern = json.loads(ledPattern)
            remoteSend(ledPattern)
            if is_raspberry_pi() == True:
                ledPattern = prepJsonRemote(ledMdl, scnPat, True)
                ledPattern = ledPattern.replace("\"",'"')
                ledPattern = json.dumps(str(ledPattern))
                ledPattern = json.loads(ledPattern)
                insert_LEDJSON(ledPattern)
                threaderLED()
    else:
        ledPattern = f'{{"patterns\": [{{"type": "solid", "color": [0,0,0]}}]}}'
        ledPattern = json.dumps(str(ledPattern))
        ledPattern = json.loads(ledPattern)
        remoteSend(ledPattern)
        if is_raspberry_pi() == True:
            insert_LEDJSON(ledPattern)
            threaderLED()
                
    #added for the Kill Queue Command
    # if id == "-1":
    #     ledPattern = f'{{"patterns\": [{{"type": "solid", "color": [0,0,0]}}]}}'
    #     ledPattern = json.dumps(str(ledPattern))
    #     ledPattern = json.loads(ledPattern)
    #     remoteSend(ledPattern)
    #     #TEST
    #     wled_Off()
    #     #TEST
    #     if is_raspberry_pi() == True:
    #         insert_LEDJSON(ledPattern)
    #         threaderLED()
        
    #time.sleep(1)
    appsettingAudioPlayFlagUpdate(1)
    appsettingVideoPlayFlagUpdate(1)
    queue_next()
    return redirect(url_for('main.home'))

@main.route('/receive_led_patterns', methods=['POST'])
def receive_led_patterns():
    try:
        json_data = json.dumps(request.get_json())
        create_table()
        #json_dataB = bytes(json_data, 'utf-8')
        insert_LEDJSON(json_data)
        threaderLED()
        #x = threading.Thread(target=apply_patterns_from_json(json.loads(json_data))).start()
        #apply_patterns_from_json(json.loads(json_data))
        print("Message Received\r")

        return jsonify({'message': 'LED patterns received and applied'})

    except Exception as e:
        return jsonify({'error': str(e)}), 500
    
@main.route('/nextsong', methods=["GET","POST"])
def nextsong():
    PlayerBl = True
    appsettingAudioPlayFlagUpdate(1)
    queue_next()
    #time.sleep(1)
    return "'message': 'next song'"

@main.route('/nextvideo', methods=["GET","POST"])
def nextvideo():
    PlayerVideoBl = True    
    appsettingVideoPlayFlagUpdate(1)
    queueVideo_next()
    #time.sleep(1)
    return "'message': 'next Video'"

@main.route('/killqueue', methods=["GET","POST"])
def killqueue():
    queue_kill()
    time.sleep(5)
    return "'message': 'queue killed'"


@main.route('/isAlive', methods=["GET"])
def isAlive():

    rowWatchManage = CRUD_tblAppSettings(['WatchManage'],"byName")
    watchManage = rowWatchManage[0][2] if rowWatchManage else 1
    return jsonify({'isAlive': 'true', 'pid': arr[0], 'WatchManage': watchManage})


@main.route('/video_seek', methods=['POST'])
def video_seek():
    value = request.json['value']
    command = f"echo seek {value} | socat - /tmp/mpvsocket"
    os.system(command)
    return jsonify({'success': True})

@main.route('/video_stopstart', methods=['POST'])
def video_stopstart():
    command = f"echo cycle pause | socat - /tmp/mpvsocket"
    os.system(command)
    return jsonify({'success': True})