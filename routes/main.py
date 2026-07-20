from flask import Blueprint, render_template,redirect,url_for,  request, abort, jsonify, json
from extensions import *

from sql import *
from procutil import pid_alive
from models.mediaMetadata import tblmediametadata
from multiprocessing import Process, Value, Array
import threading
import time
from ledPlayer import *
from sys import platform
import platform
from remotes import *
import relay_broadcaster
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
        # songQCnt/videoQCnt keep their historic slot; QDur adds the queued
        # seconds so the pill bar can show total remaining time.
        dataDict.append({item[0]: item[1], item[0].replace('QCnt', 'QDur'): item[2]})
    #print(dataDict)
    return jsonify(dataDict)


@main.route('/api/mediameta/<media_type>/<int:media_id>')
def mediameta(media_type, media_id):
    """Full extracted metadata for one media row — feeds the table info modal."""
    if media_type not in ('music', 'video'):
        abort(400)
    m = tblmediametadata.query.filter_by(media_type=media_type, media_id=media_id).first()
    if not m:
        return jsonify(None)
    d = m.to_dict()
    # local cached copy first (works offline), remote URL as fallback
    from thumbs import store as thumb_store
    d['thumbnail'] = thumb_store.url(media_type, media_id) or d.get('thumbnail')
    return jsonify(d)


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
    # flname is an OPTIONAL display-name override — kept human-readable; the
    # legacy no-video-id path scrubs it into a safe filename itself
    # (sql._enqueue_legacy).
    flname = (data.get('flname') or '').strip()
    mediaType = data['mediaType']
    scene_ID = data['scene_ID']
    addMediaToYT_que(url,flname, mediaType, scene_ID)
    return jsonify('Success')#jsonf'Success'
def addMediaToYT_que(url, flname, mediaType, scene_ID):
    """Intake entry point (form + Chrome extension). A playlist URL is queued for
    background expansion; a single video is deduped by its YouTube id and shares
    one media row/file across scenes. `flname` is an OPTIONAL display-name override
    (blank → metadata supplies the name). See sql.enqueue_single / enqueue_playlist.

    NOTE: pass the RAW url here (do NOT pre-strip &list=) so playlists are detected."""
    from ytid import is_playlist_url
    media_type = 'music' if mediaType == 'mp3' else 'video'
    if is_playlist_url(url):
        return enqueue_playlist(url, media_type, scene_ID)
    return enqueue_single(url, mediaType, scene_ID, flname or '')

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
        
# Serializes scene activations. Two overlapping runs (double-click, or a click
# while the previous activation is still inside its multi-second WLED/remote
# push window) interleave their play-flag writes — player_debug.log caught one
# leaving the flags OFF permanently, wedging playback until an app restart.
# The lock makes clicks queue up instead: last click still wins.
_activate_lock = threading.Lock()


@main.route('/activatescenes/', methods=['GET', 'POST'])
def activatescene():
    id = request.args.get('id')
    with _activate_lock:
        _activate_scene(id)
    return redirect(url_for('main.home'))


def _players_alive():
    """True if either mpv is still up. Killing a live player is only HALF a
    stop: the spawner thread notices the dead mpv up to ~1 s later and THEN
    runs update_*_data_entry, which sets que=0 on the killed track — silently
    clobbering any requeue issued in that window. player_debug.log showed the
    whole chain on a one-song scene: kill, requeue, mpv EXIT, dequeue, empty
    queue, spawner turns its own play flag off, silence until the next click.
    Callers that kill a live player must sleep out that window BEFORE
    touching que flags."""
    try:
        if pid_alive(int(appsettingAudioPlayPID()[0][2])):
            return True
    except Exception:
        return True   # can't tell -> assume the worst and take the wait
    try:
        return pid_alive(int(appsettingVideoPlayPID()[0][2]))
    except Exception:
        return True


# Spawner poll interval (1 s) + margin: how long after a kill until the
# killed track's update_*_data_entry dequeue has definitely landed.
_UNWIND_SECONDS = 2.5


def _restart_players(scene_id):
    """Re-click of the ALREADY-ACTIVE scene: no queue_kill (whatever is still
    queued stays queued), no device pushes (the lights already show this
    scene) — bounce the players, then top the queue back up so the spawners
    restart from the top.

    Order matters, twice over: the requeue must come AFTER the killed track's
    dequeue has unwound (see _players_alive) or it gets clobbered, and the
    play flags must be forced ON at the end because a spawner whose queue ran
    dry turned its own flag OFF — killing mpv alone leaves a drained player
    silent forever."""
    was_playing = _players_alive()
    queue_next()
    queueVideo_next()
    if was_playing:
        time.sleep(_UNWIND_SECONDS)
    selected = [row[2] for row in get_MusicSceneSongs_BYSceneID(scene_id)]
    if selected:
        update_play_queue_selected(selected)
    selectedVideo = [row[2] for row in get_VideoScene_BYSceneID(scene_id)]
    if selectedVideo:
        update_video_queue_selected(selectedVideo)
    appsettingAudioPlayFlagUpdate(1)
    appsettingVideoPlayFlagUpdate(1)


def _activate_scene(id):
    try:
        scene_id = int(id)
    except (TypeError, ValueError):
        scene_id = None
    # Every scene start wipes the sticky failure badges (LED-remote / WLED /
    # relay) BEFORE any pushes run: a device that fails during THIS
    # activation re-raises its badge within seconds, while a badge left over
    # from a device the operator has since disabled stays silenced.
    appsettingSet('remote_send_last_fail', '')
    appsettingSet('wled_send_last_fail', '')
    appsettingSet('relay_push_last_drop', '')
    # Same scene clicked again -> restart playback, keep the queue. The full
    # teardown below is only for a genuine scene CHANGE (id guard skips the
    # kill-queue pseudo-scene -1, which must always tear down).
    if scene_id is not None and scene_id > 0 \
            and appsettingGetCurrentScene() == scene_id:
        _restart_players(scene_id)
        return
    # Record the active scene so playback picks THIS scene's per-link volume/order/
    # screen/loops for media rows now shared across scenes (video-id dedup).
    if scene_id is not None:
        appsettingSetCurrentScene(scene_id)
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
    
    # Pause the SPAWNERS before swapping queues. The player threads free-run
    # on a 1 s poll: with the play flags left ON they notice queue_kill's
    # dead mpv and spawn the NEXT track while this route is still mid-swap
    # (the LED/WLED pushes below make that window ~4 s) — and the
    # queue_next() at the end then executed the newborn. player_debug.log
    # showed it on every switch: kill at T, spawn at T+1.5, kill at T+4.
    # Flags go back ON at the very end, after queue_next has cleared any
    # straggler from the OLD queue.
    appsettingAudioPlayFlagUpdate(0)
    appsettingVideoPlayFlagUpdate(0)
    was_playing = _players_alive()
    queue_kill()
    # From here to `finally` the spawners are paused: if ANYTHING below throws
    # (a device push, a queue update), the flags MUST still come back on or
    # playback stays wedged until an app restart. try/finally guarantees it.
    try:
        # Same clobber race as _restart_players: the killed track's que=0
        # dequeue lands ~1 s after queue_kill's pkill and would knock that
        # track out of the NEW queue if it belongs to the new scene too.
        if was_playing:
            time.sleep(_UNWIND_SECONDS)
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
        # Mirror the scene's WLED lighting (or lights-off) to remote players'
        # home WLED controllers via the relay
        relay_broadcaster.broadcast_wled(data)

        if ledMdl is not None and len(ledMdl) > 0:
                ledPattern = prepJsonRemote(ledMdl, scnPat)
                ledPattern = ledPattern.replace("\"",'"')
                ledPattern = json.dumps(str(ledPattern))
                ledPattern = json.loads(ledPattern)
                remoteSend(ledPattern)
                relay_broadcaster.broadcast_led(ledPattern)
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
            relay_broadcaster.broadcast_led(ledPattern)
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

    finally:
        # Order matters: queue_next clears any old-queue straggler FIRST; only
        # then do the play flags release the spawners onto the NEW queue.
        queue_next()
        appsettingAudioPlayFlagUpdate(1)
        appsettingVideoPlayFlagUpdate(1)

# Preflight headers for browser-origin LED pushes (remote players' portal
# pages POST here across their LAN). Access-Control-Allow-Origin and
# Allow-Headers are already ADDED to every response by the blueprint-wide
# after_request above — repeating them here would duplicate the header and
# make browsers reject the response. Allow-Private-Network answers Chrome's
# private-network-access preflight for HTTPS pages calling a LAN address.
_LED_CORS = {
    'Access-Control-Allow-Methods': 'POST, OPTIONS',
    'Access-Control-Allow-Private-Network': 'true',
    'Access-Control-Max-Age': '86400',
}

@main.route('/receive_led_patterns', methods=['POST', 'OPTIONS'])
def receive_led_patterns():
    if request.method == 'OPTIONS':   # CORS/PNA preflight from a portal page
        return ('', 204, _LED_CORS)
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
    
@main.route('/api/nowplaying', methods=['GET'])
def nowplaying():
    """Dashboard poll: current song/video (human display names) + active scene."""
    return jsonify(get_now_playing())

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


# Transport controls: each mpv instance is addressed by its own IPC socket
# (video: mpvsocket-video / music: mpvsocket-music, see mpv.sh / mpvAudio.sh).
# The transport itself lives in mpv_ipc so sql.py's kill helpers can share it
# (they fade the music out through the same socket before killing).
from mpv_ipc import mpv_command as _mpv_command

@main.route('/video_seek', methods=['POST'])
def video_seek():
    value = request.json['value']
    _mpv_command('video', f'seek {value}')
    return jsonify({'success': True})

@main.route('/video_stopstart', methods=['POST'])
def video_stopstart():
    _mpv_command('video', 'cycle pause')
    return jsonify({'success': True})

@main.route('/music_seek', methods=['POST'])
def music_seek():
    value = request.json['value']
    _mpv_command('music', f'seek {value}')
    return jsonify({'success': True})

@main.route('/music_stopstart', methods=['POST'])
def music_stopstart():
    _mpv_command('music', 'cycle pause')
    return jsonify({'success': True})