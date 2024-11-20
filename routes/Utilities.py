from flask import Blueprint, render_template, request, abort, jsonify, json, redirect, url_for
from extensions import db
from extensions2 import *
from sql import *
from ipsearch import *
from ledPlayer import *
from sys import platform
import alsaaudio

from ytProcess import yt_process
from pathlib import Path
from models.scenes import tblscenes as sc
from routes.main import addMediaToYT_que, sanitize_filename

ut = Blueprint('ut', __name__)

def remove_list_param(input_str):
    if '&list' in input_str:
        return input_str.split('&list')[0]
    return input_str

@ut.route('/utilities',methods=['GET', 'POST'])
def main():
    if request.method == 'POST':
        pass
        if request.form['submit'] == 'Process Youtube':
            url = request.form['URLLink']
            url = remove_list_param(url)
            flname = request.form['FileName']
            flname = sanitize_filename(flname)
            scene_ID = request.form.get("Scene")
            mediaType = request.form.get("Media")
            addMediaToYT_que(url,flname, mediaType, scene_ID)
            
            return  redirect(url_for('main.home'))
        elif request.form['submit'] == 'Ping Network':
            startPinging()
            return  redirect(url_for('main.home'))
        elif request.form['submit'] == 'Restart Computer':
            restartComputer()
            return  redirect(url_for('main.home'))
        else:
            pass

    scenes = sc.query.with_entities(sc.scene_ID, sc.sceneName).order_by(sc.sceneName).all()
    scenes.insert(0, (0, "None"))
    data = select_data_stats()#arr)
    mixer = alsaaudio.Mixer("Master")
    volume = mixer.getvolume()[0]
    return render_template('utils.html',items=data,volume=volume,Scenes=scenes)

    
@ut.route('/processyt', methods=['GET'])
def processyt():
    url = request.form['URLLink']
    url = remove_list_param(url)
    #print(url)
    flname = request.form['FileName']
    #print(flname)
    yt_process(url,flname)
    mixer = alsaaudio.Mixer("Master")
    volume = mixer.getvolume()[0]
    return render_template('utils.html',volume=volume)
