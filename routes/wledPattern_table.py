from flask import Blueprint, render_template, request, abort, jsonify, json, redirect, url_for
from models.wledPattern import  tblwledpattern as tbl
from models.scenes import tblscenes as sc
from models.wledPattern import tbleffect as ef
from models.wledPattern import tblpallette as pt

import alsaaudio
from extensions import *

from sql import *
from wLed.wledCommand import setWledEffect

wl = Blueprint('wl', __name__)

tblColumns = ['wledPattern_ID', 'scene_ID','server_ID', 'effect', 'pallette', 'color1', 'color2', 'color3', 'speed', 'brightness', 'orderBy']
primeKey = tblColumns[0]
@wl.route('/wledPallette')
def edittbl():
    data = select_data_stats()#arr)
    mixer = alsaaudio.Mixer("Master")
    volume = mixer.getvolume()[0]
    scenes = sc.query.with_entities(sc.scene_ID, sc.sceneName).order_by(sc.sceneName).all()
    sceneFilter = appsettingGetSceneFilter()
    return render_template('wledPattern_table.html',items=data,volume=volume,scenes=scenes,sceneFilter=int(sceneFilter[0][0]))

@wl.route('/api/effects')
def effect():
    query = ef.query.order_by(ef.effectName)
    return {'data': [ef.to_dict() for ef in query]}


@wl.route('/api/pallettes')
def pallette():
    query = pt.query.order_by(pt.palletteName)
    return {'data': [pt.to_dict() for pt in query]}

@wl.route('/api/WLEDTest', methods=['POST'])
def WLEDTest():
    jdata = request.get_json()
    #print(jdata)
    
    data = getWledPatternBywledID(jdata[primeKey])
    if data is not None:
        for row in data:
            #print(row.effect)
            setWledEffect(row.effect,row.pallette,row.color1, row.color2, row.color3, row.speed, row.brightness, row.server_ID)
    return '', 204


@wl.route('/api/wledPattern')
def data():
    sceneFilter = appsettingGetSceneFilter()
    if int(sceneFilter[0][0]) != 0:
        query = tbl.query.filter(tbl.scene_ID == int(sceneFilter[0][0])).order_by(tbl.wledPattern_ID.desc())
    else:
        query = tbl.query.order_by(tbl.scene_ID)
 
    # search filter
    search = request.args.get('search')
    if search:
        querysc = sc.query.filter(db.or_(
            sc.sceneName.like(f'%{search}%')))
          
        scene_dis_list = [rows.scene_ID for rows in querysc.all()]
        
        #(scene_dis_list)
        query = tbl.query.filter(db.or_(
            tbl.scene_ID.in_(scene_dis_list)
        ))
        #///
    total = query.count()

    # sorting
    sort = request.args.get('sort')
    if sort:
        order = []
        for s in sort.split(','):
            direction = s[0]
            name = s[1:]
            if name not in tblColumns:
                name = primeKey
            col = getattr(tbl, name)
            if direction == '-':
                col = col.desc()
            order.append(col)
        if order:
            if int(sceneFilter[0][0]) != 0:
                query = tbl.query.filter(tbl.scene_ID == int(sceneFilter[0][0])).order_by(*order)
            else:
                query = tbl.query.order_by(*order)

    # pagination
    start = request.args.get('start', type=int, default=-1)
    length = request.args.get('length', type=int, default=-1)
    if start != -1 and length != -1:
        query = query.offset(start).limit(length)

    # response
    return {
        'data': [tbl.to_dict() for tbl in query],
        'total': total,
    }

@wl.route('/api/wledPattern', methods=['POST'])
def update():
    data = request.get_json()
    #print(data)
    if primeKey not in data:
        abort(400)
    TSP = tbl.query.get(data[primeKey])
    for field in tblColumns:
        if field in data:
            setattr(TSP, field, data[field])
    db.session.commit()
    return '', 204

@wl.route('/api/wledpatternaddrow')
def wledaddrow():
    sceneFilter = appsettingGetSceneFilter()
    newrow = tbl(scene_ID=int(sceneFilter[0][0]), server_ID=0, effect=0, pallette=0, color1='[0,0,0]', color2='[0,0,0]', color3='[0,0,0]', speed=125, brightness=125, orderBy=1)
    db.session.add(newrow)
    db.session.commit()
    return 'tblwledPattern has a new row'

@wl.route('/api/wledpatterndelrow', methods=['POST'])
def wleddelrow():
    data = request.get_json()
   #print(data)
    if primeKey not in data:
        abort(400)
    TSP = tbl.query.get(data[primeKey])
    db.session.delete(TSP)
    db.session.commit()    
    return 'tblwledPattern row ' + data[primeKey] + ' has been deleted'

def getWledPatternBySceneID(sceneID):
    return tbl.query.filter(tbl.scene_ID == sceneID).all()

def getWledPatternBywledID(wledID):
    return tbl.query.filter(tbl.wledPattern_ID == wledID).all()