#!/usr/bin/env python3
from sql import *
from player import *
from speech import *
from ledPlayer import *
from ipsearch import *
from ytProcess import yt_process
from multiprocessing import Process, Value, Array
import alsaaudio
#import multiprocessing as mp
import time

from flask import Flask, render_template, request, url_for, redirect, session, jsonify, json

# Initialize the Flask application
app = Flask(__name__)

num = Value('i', 0)
arr = Array('i', range(10))

arr[0] = os.getpid()
arr[1] = 0 #volume 
arr[2] = 0  #current song
arr[3] = 0  #previous song
print(arr[0])

@app.route('/update/<pk>', methods=['GET', 'POST'])
def music_update(pk):
    print("hi")
    return render_template('music_update.html',pk=pk)


@app.route("/set_volumeold", methods=["POST"])
def set_volumeold():
    json_data = json.loads(json.dumps(request.get_json()))
    new_volume = int(json_data["volume"])
    mixer = alsaaudio.Mixer("Master")
    mixer.setvolume(new_volume)
    return "Volume set successfully!"

@app.route('/receive_led_patterns', methods=['POST'])
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

# Define a route for the default URL, which loads the form
@app.route('/')
def form():
    create_table()
    data = select_data_stats(arr)
    mixer = alsaaudio.Mixer("Master")
    volume = mixer.getvolume()[0]
    scenes = get_Scenes()
    return render_template('home.html',items=data, Scenes=scenes ,volume=volume)

def startTheadPlayer():
    create_table()
    data = select_data_stats(arr)
    \
    p = Process(target=threader, args=(num, arr))
    p.start()
    
    
@app.route('/', methods=['GET', 'POST'])
def controls():
##   session.init_app(app)
   if request.method == 'POST':
        session.permanent = True
        app.permanent_session_lifetime = timedelta(minutes=1)
        mixer = alsaaudio.Mixer("Master")
        volume = mixer.getvolume()[0]
        if request.form['submit'] == 'Play By Name':
            song = request.form['song']
            if len(song) > 0:
                songCount = update_play_queue(song)
                num.value = 1
                print("Play By Name")
                time.sleep(1)
            return redirect(url_for('controls'))                    
            pass # do something
        elif request.form['submit'] == 'Play Text':
            texttosend = request.form['texttospeech']
            songCount = TextToSpeechPlay(texttosend)
            num.value = 1
            print("Text to Speech")
            time.sleep(1)
            return redirect(url_for('controls'))                    
            pass # do something
        elif request.form['submit'] == 'Find and Store All Songs':
            password = request.form['password']
            #if password == "":
            create_table()
            queue_kill()
            num.value = 0
            drop_table('tblMusic')
            create_table()
            find_store_files()
            print("Find All")
            return redirect(url_for('controls'))
            pass # do something else
        elif request.form['submit'] == 'Kill Queue':
            create_table()
            num.value = 0
            queue_kill()
            print("Kill")
            time.sleep(1)
            return redirect(url_for('controls'))
            pass # do something else
        elif request.form['submit'] == 'Next Song':
            create_table()
            num.value = 1
            queue_next()
            print("Next")
            #time.sleep(2)
            return redirect(url_for('controls'))
            pass # do something else
        elif request.form['submit'].__contains__('Submit Scene ID'):
            _scene_ID = []
            _scene_ID.append(int(request.form['submit'].replace('Submit Scene ID','')))
            scnPat = CRUD_tblScenePattern(_scene_ID,"R")
            #print(scnPat)
            ledMdl = CRUD_tblLEDTypeModel([scnPat[0][2]],"R")
            #get all songs associated with scene
            rows = get_MusicSceneSongs_BYSceneID(_scene_ID[0])
            queue_off()
            selected = []
            if len(rows) > 0:
                for row in rows:
                    #print(row[2])
                    selected.append(row[2])
                update_play_queue_selected(selected)
            
            #build json for led
            rows = CRUD_tblMusicScene(_scene_ID,"R") 
            i=0
            if len(ledMdl) > 0:
                ledPattern = f'{{"patterns\": [{{\"type\": \"{str(ledMdl[0][1])}\"'
                tester = ""
                for row in ledMdl:
                    #print(row[2])
                    tester = str(row[2])
                    if tester.find("color")>0:
                        ledPattern += ', \"color\": ' + str(scnPat[i][3]) 
                    if tester.find("wait_ms")>0:
                        ledPattern += ', \"wait_ms\": ' + str(scnPat[i][4])
                    if tester.find("iterations")>0:
                        ledPattern += ', \"iterations\": ' + str(scnPat[i][5])
                    if tester.find("direction")>0:
                        ledPattern += ', \"direction\": ' + str(scnPat[i][6])
                    if tester.find("cdiff")>0:
                        ledPattern += ', \"cdiff\": ' + str(scnPat[i][7])
                    i+=1
                    if i < len(rows):
                        ledPattern += ","
            ledPattern += '},{"type": "solid", "color": [0,0,0]}]}'
            ledPattern = ledPattern.replace("\"",'"')
            ledPattern = json.dumps(str(ledPattern))
            ledPattern = json.loads(ledPattern)
            #print(ledPattern)
            insert_LEDJSON(ledPattern)
            threaderLED()
            #time.sleep(1)
            num.value = 1
            queue_next()
            #time.sleep(2)
            return redirect(url_for('controls'))
            pass # do something else
        elif request.form['submit'] == 'Go to Controls':
            return render_template('control.html')
        elif request.form['submit'] == 'Text to Speech':
            return render_template('tts.html')
        elif request.form['submit'] == 'Utilities':
            return render_template('utils.html')
        elif request.form['submit'] == 'ProcessLink':
            url = request.form['URLLink']
            print(url)
            flname = request.form['FileName']
            print(flname)
            yt_process(url,flname)
            return redirect(url_for('controls'))
            pass
        elif request.form['submit'] == 'loadtestdata':
            loadDefaults()
            return redirect(url_for('controls'))
            pass
        elif request.form['submit'] == 'PingNetwork':
            startPinging()
            return redirect(url_for('controls'))
            pass
        elif request.form['submit'] == 'Show All Songs':
            data = select_data_allsongs()
            return render_template('AllSongs.html',items=data)
        elif request.form['submit'] == 'Add to Queue':
            selected_songs = request.form.getlist("songs")
            #print(len(selected_songs))
            if (len(selected_songs)>0):
                update_play_queue_selected(selected_songs)
                num.value = 1
                time.sleep(1)
            return redirect(url_for('controls'))
        elif request.form['submit'] == 'Delete Selected':
            selected_songs = request.form.getlist("songs")
            password = request.form['password']
            if password == "":
                #if (len(selected_songs)>0):
                delete_songs(selected_songs)
                num.value = 1
                time.sleep(1)
                print("Deleted File")
            return redirect(url_for('controls'))
            pass # unknown
   data = select_data_stats(arr)
   scenes = get_Scenes()
   return render_template('home.html',items=data, Scenes=scenes ,volume=volume)
   
# Run the app :)
if __name__ == '__main__':
  startTheadPlayer()
  app.secret_key = 'super secret key'
  app.config['SESSION_TYPE'] = 'filesystem'
  app.run(
        threaded=True,
        #debug=True,
        host="0.0.0.0",
        port=int("8088")
  )
