from flask import Blueprint, render_template, request, abort, jsonify, json, redirect, url_for
from extensions import *

from models.scenes import tblscenes as tbl
from sql import *
import alsaaudio



# cid  name         type     notnull  dflt_value  pk
# ---  -----------  -------  -------  ----------  --
# 0    scene_ID     INTEGER  0                    1 
# 1    sceneName    TEXT     0                    0 
# 2    active       INT      0                    0 
# 3    orderBy      INT      0                    0 
# 4    campaign_id  INT      0                    0 

sn = Blueprint('sn', __name__)
tblColumns = ['scene_ID','sceneName', 'active','orderBy','campaign_id']
primeKey = tblColumns[0]

@sn.after_request
def add_headers(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
    response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS') # Explicitly list allowed methods
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response

@sn.route('/scenes')
def edittbl():
    data = select_data_stats()#arr)
    mixer = alsaaudio.Mixer("Master")
    volume = mixer.getvolume()[0]
    return render_template('scenes_table.html',items=data,volume=volume)


@sn.route('/api/scenes')
def data():
    query = tbl.query.order_by(tbl.sceneName)
    search = request.args.get('search')
    
    if search:
        query = query.filter(db.or_(
            tbl.sceneName.like(f'%{search}%')
        ))
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

@sn.route('/api/scenes', methods=['POST'])
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

@sn.route('/api/scenesaddrow', methods=['POST'])
def scenesaddrow():
    row = [' ',1,1,1]
    CRUD_tblScenes(row,"C")
    return 'tblScenes has a new row'

@sn.route('/api/scenesdelrow', methods=['POST'])
def scenesdelrow():
    data = request.get_json()
    #print(data)
    if primeKey not in data:
        abort(400)
    row = [data[primeKey]]
    CRUD_tblScenes(row,"D")
    return 'tblScenes row ' + data[primeKey] + ' has been deleted'

@sn.route('/api/sceneFilter', methods=['POST'])
def sceneFilter():
    data = request.get_json()
    appsettingSetSceneFilter(int(data['scene_id']))
    return '', 204
    