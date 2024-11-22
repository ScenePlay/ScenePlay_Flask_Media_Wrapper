
from flask import Blueprint, render_template, request, abort, jsonify, json, redirect, url_for
from models.videoScene import tblvideoscene as tbl
from models.scenes import tblscenes as sc
import alsaaudio
from extensions import db
from extensions2 import *
from sql import *

# cid  name              type     notnull  dflt_value  pk
# ---  ----------------  -------  -------  ----------  --
# 0    videoScene_ID     INTEGER  0                    1 
# 1    scene_ID          INT      0                    0 
# 2    video_ID          INT      0                    0 
# 3    DisplayScreen_ID  INT      0                    0 
# 4    orderBy           INT      0                    0 
# 5    volume            INT      0                    0 


vs = Blueprint('vs', __name__)
tblColumns = ['videoScene_ID','scene_ID', 'video_ID','DisplayScreen_ID','orderBy','volume','loops']
primeKey = tblColumns[0]

@vs.route('/videoScene')
def edittbl():
    data = select_data_stats()#arr)
    mixer = alsaaudio.Mixer("Master")
    volume = mixer.getvolume()[0]
    scenes = sc.query.with_entities(sc.scene_ID, sc.sceneName).order_by(sc.sceneName).all()
    sceneFilter = appsettingGetSceneFilter()
    return render_template('videoScene_table.html',items=data,volume=volume,scenes=scenes,sceneFilter=int(sceneFilter[0][0]))

@vs.route('/api/videoScene', methods=['GET'])
def data():
    sceneFilter = appsettingGetSceneFilter()
    if int(sceneFilter[0][0]) != 0:
        query = tbl.query.filter(tbl.scene_ID == int(sceneFilter[0][0])).order_by(tbl.videoScene_ID.desc())
    else:
        query = tbl.query.order_by(tbl.scene_ID)
    # search filter
    search = request.args.get('search')
    if search:
        #//// Updated query from Scenes Search
        querysc = sc.query.filter(db.or_(
            sc.sceneName.like(f'%{search}%')))
          
        scene_dis_list = [rows.scene_ID for rows in querysc.all()]
        
        #print(scene_dis_list)
        query = tbl.query.filter(db.or_(
            tbl.scene_ID.in_(scene_dis_list)
        )).order_by(tbl.orderBy)
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

@vs.route('/api/videoScene', methods=['POST'])
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


@vs.route('/api/videoSceneaddrow')
def videoSceneaddrow():
    sceneFilter = appsettingGetSceneFilter()
    row = [int(sceneFilter[0][0]),0,0,1,100,0]
    CRUD_tblVideoScene(row,"C")
    return 'tblvideoScene has a new row'

@vs.route('/api/videoScenedelrow', methods=['POST'])
def videoScenedelrow():
    data = request.get_json()
    #print(data)
    if primeKey not in data:
        abort(400)
    row = [data[primeKey]]
    CRUD_tblVideoScene(row,"D")
    return 'tblvideoScene row ' + data[primeKey] + ' has been deleted'
