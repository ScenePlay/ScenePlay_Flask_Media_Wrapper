from flask import Blueprint, render_template, request, abort, jsonify, json, redirect, url_for
from extensions import *

from models.scenes import tblscenes as tbl
from sql import *



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
    from routes._util import campaigns_for_filter
    data = select_data_stats()#arr)
    volume = currentvolume()
    return render_template('scenes_table.html',items=data,volume=volume,
                           campaigns=campaigns_for_filter(),
                           campaignFilter=appsettingGetCampaignFilter())


@sn.route('/api/scenes')
def data():
    query = tbl.query

    # Campaign filter: the same persistent global setting (CampaignFilter)
    # the media/scene-link table pages use — one selection scopes them all.
    campaign = appsettingGetCampaignFilter()
    if campaign:
        query = query.filter(tbl.campaign_id == campaign)

    search = request.args.get('search')
    if search:
        query = query.filter(db.or_(
            tbl.sceneName.like(f'%{search}%')
        ))
    total = query.count()

    # sorting — applied ON the filtered query (rebuilding from tbl.query here
    # used to silently drop the search/campaign filters)
    sort = request.args.get('sort')
    order = []
    if sort:
        for s in sort.split(','):
            direction = s[0]
            name = s[1:]
            if name not in tblColumns:
                name = primeKey
            col = getattr(tbl, name)
            if direction == '-':
                col = col.desc()
            order.append(col)
    query = query.order_by(*order) if order else query.order_by(tbl.sceneName)

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
    TSP = db.session.get(tbl, data[primeKey])
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


@sn.route('/api/campaignFilter', methods=['POST'])
def campaignFilter():
    """Set the global campaign filter (0=all, -1=no campaign). Changing the
    campaign always RESETS the scene filter: the scene dropdown re-populates
    with only that campaign's scenes, so a stale cross-campaign scene pick
    can't leave the tables showing nothing."""
    data = request.get_json()
    appsettingSetCampaignFilter(int(data['campaign_id']))
    appsettingSetSceneFilter(0)
    return '', 204
    