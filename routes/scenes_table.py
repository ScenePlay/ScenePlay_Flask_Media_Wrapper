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
    from routes._util import campaigns_for_filter, scenes_for_filter
    data = select_data_stats()#arr)
    volume = currentvolume()
    campaignFilter = appsettingGetCampaignFilter()
    sceneFilter = appsettingGetSceneFilter()
    return render_template('scenes_table.html',items=data,volume=volume,
                           campaigns=campaigns_for_filter(),
                           campaignFilter=campaignFilter,
                           scenes=scenes_for_filter(campaignFilter),
                           sceneFilter=int(sceneFilter[0][0]))


@sn.route('/api/scenes')
def data():
    query = tbl.query

    # Scene/campaign filters: the same persistent global settings the
    # media/scene-link table pages use — one selection scopes them all.
    sceneF = int(appsettingGetSceneFilter()[0][0])
    campaign = appsettingGetCampaignFilter()
    if sceneF:
        query = query.filter(tbl.scene_ID == sceneF)
    elif campaign:
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

    # response — plus the play-queue state of each scene's media for the
    # grid's Queue checkbox ('all' / 'some' / 'none' / '' = nothing playable)
    from sql import scene_queue_state
    import smart_scenes
    from extensions import database
    rules = {x['scene_id']: x['summary'] for x in smart_scenes.list_rules(database)}
    rows = []
    for r in query:
        d = r.to_dict()
        d['queued'] = scene_queue_state(r.scene_ID)
        d['rule'] = rules.get(r.scene_ID, '')      # '' = a plain, hand-built scene
        rows.append(d)
    return {
        'data': rows,
        'total': total,
    }


@sn.route('/api/scenes/unlink-rule', methods=['POST'])
def unlink_rule():
    """Turn a smart scene back into a plain one: the rule goes, the scene and
    every song it holds stay."""
    import smart_scenes
    from extensions import database
    data = request.get_json(silent=True) or {}
    try:
        sid = int(data.get('scene_ID') or 0)
    except (TypeError, ValueError):
        sid = 0
    if not sid:
        abort(400)
    smart_scenes.drop_rule(database, sid)
    return jsonify({'ok': True})


@sn.route('/api/scenes/queue-states')
def queue_states():
    """Home page poll: {scene_ID: all|some|none} so the cards' Queue toggles
    track what the players have consumed."""
    from sql import scene_queue_states
    return jsonify({'ok': True, 'states': scene_queue_states()})


@sn.route('/api/scenes/queue', methods=['POST'])
def queue_toggle():
    """{scene_ID, queued: bool} — put a scene's songs/videos into the play
    queue (or pull them out) without activating the scene."""
    from sql import queue_scene_songs, scene_queue_state
    data = request.get_json(silent=True) or {}
    try:
        scene_id = int(data.get('scene_ID') or 0)
    except (TypeError, ValueError):
        scene_id = 0
    if not scene_id:
        abort(400)
    changed = queue_scene_songs(scene_id, bool(data.get('queued')))
    return jsonify({'ok': True, 'changed': changed, 'queued': scene_queue_state(scene_id)})

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
    # The page asks whether the new scene joins the selected campaign and
    # sends campaign_id (0 = leave unassigned); bodiless calls keep the
    # historical default of campaign 1.
    data = request.get_json(silent=True) or {}
    row = [' ',1,1,int(data.get('campaign_id', 1))]
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
    from routes._util import scenes_for_filter
    data = request.get_json()
    scene_id = int(data['scene_id'])
    appsettingSetSceneFilter(scene_id)
    # Picking a scene drags the campaign filter along to THAT scene's
    # campaign, so the two dropdowns always agree. A scene without a
    # campaign resets the campaign filter to All — that's the only value
    # that can still show it. Scene 'All' (0) leaves the campaign alone.
    # The response carries the resulting campaign and its scene list so
    # site.js can re-sync the dropdowns and table in place, no reload.
    if scene_id:
        scene = db.session.get(tbl, scene_id)
        appsettingSetCampaignFilter((scene.campaign_id or 0) if scene else 0)
    campaign = appsettingGetCampaignFilter()
    return jsonify(campaign_id=campaign,
                   scenes=[list(s) for s in scenes_for_filter(campaign)])


@sn.route('/api/campaignFilter', methods=['POST'])
def campaignFilter():
    """Set the global campaign filter (0=all). Changing the campaign always
    RESETS the scene filter: the scene dropdown re-populates with only that
    campaign's scenes, so a stale cross-campaign scene pick can't leave the
    tables showing nothing. Returns the (clamped) campaign and its scene
    list so site.js can re-sync the dropdowns and table in place."""
    from routes._util import scenes_for_filter
    data = request.get_json()
    appsettingSetCampaignFilter(int(data['campaign_id']))
    appsettingSetSceneFilter(0)
    campaign = appsettingGetCampaignFilter()
    return jsonify(campaign_id=campaign,
                   scenes=[list(s) for s in scenes_for_filter(campaign)])
    