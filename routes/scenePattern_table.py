
from flask import Blueprint, render_template, request, abort, jsonify, json, redirect, url_for
from models.scenePattern import  tblscenepattern as tbl
from models.scenes import tblscenes as sc
import alsaaudio
from extensions import db
from extensions2 import *
from sql import *
from remotes import *
from routes.main import is_raspberry_pi
from ledPlayer import *

# cid  name             type     notnull  dflt_value  pk
# ---  ---------------  -------  -------  ----------  --
# 0    scenePattern_ID  INTEGER  0                    1 
# 1    scene_ID         INT      0                    0 
# 2    ledTypeModel_ID  INT      0                    0 
# 3    color            TEXT     0                    0 
# 4    wait_ms          INT      0                    0 
# 5    iterations       INT      0                    0 
# 6    direction        INT      0                    0 
# 7    cdiff            TEXT     0                    0

sp = Blueprint('sp', __name__)

tblColumns = ['scenePattern_ID', 'scene_ID','ledTypeModel_ID', 'color', 'wait_ms', 'iterations', 'direction', 'cdiff']
primeKey = tblColumns[0]
@sp.route('/scenePattern')
def edittbl():
    data = select_data_stats()#arr)
    mixer = alsaaudio.Mixer("Master")
    volume = mixer.getvolume()[0]
    return render_template('scenePattern_table.html',items=data,volume=volume)

@sp.route('/api/scenePattern')
def data():
    query = tbl.query

    # search filter
    search = request.args.get('search')
    if search:
        querysc = sc.query.filter(db.or_(
            sc.sceneName.like(f'%{search}%')))
          
        scene_dis_list = [rows.scene_ID for rows in querysc.all()]
        
        #print(scene_dis_list)
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

@sp.route('/api/scenePattern', methods=['POST'])
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

@sp.route('/api/scenepatternaddrow')
def scenesaddrow():
    row = [0,0,'[0,0,0]',10,10000,1,'[0,0,0]']
    CRUD_tblScenePattern(row,"C")
    return 'tblScenePattern has a new row'

@sp.route('/api/scenepatterndelrow', methods=['POST'])
def scenesdelrow():
    data = request.get_json()
    #print(data)
    if primeKey not in data:
        abort(400)
    row = [data[primeKey]]
    CRUD_tblScenePattern(row,"D")
    return 'tblScenePattern row ' + data[primeKey] + ' has been deleted'



@sp.route('/api/RPiLEDTest', methods=['POST'])
def WLEDTest():
    jdata = request.get_json()
    #print(jdata)
    
    scnID = []
    scnID.append(int(jdata[primeKey]))
    scnPat = CRUD_tblScenePattern(scnID,"R")
    #print(scnPat)
    ledMdl = None
    if len(scnPat) > 0:
        _scene_ID = []
        _scene_ID.append(scnPat[0][1])
    #print(_scene_ID)
        _ledType_ID = []
        _ledType_ID.append(scnPat[0][2])
    #print(_ledType_ID)
        ledMdl = CRUD_tblLEDTypeModel(_ledType_ID,"R")
    
    if ledMdl is not None and len(ledMdl) > 0:
        ledPattern = prepJsonRemote(ledMdl, scnPat)
        ledPattern = ledPattern.replace("\"",'"')
        ledPattern = json.dumps(str(ledPattern))
        ledPattern = json.loads(ledPattern)
        remoteSend(ledPattern)
        if is_raspberry_pi() == True:
            insert_LEDJSON(ledPattern)
            threaderLED()
    return '', 204

def getWledPatternBywledID(RledID):
    return tbl.query.filter(tbl.ledTypeModel_ID == RledID).all()
