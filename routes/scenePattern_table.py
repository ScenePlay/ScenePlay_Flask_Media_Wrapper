"""Scene RPiLED editor.

Rows: (scenePattern_ID, scene_ID, patternType, params JSON, orderBy).
The pattern vocabulary — which parameters each type honors, labels, ranges,
defaults — comes from led_patterns.py and is served to the page by
/api/led/patterns so the editor renders only the fields that apply.
"""
import json

from flask import Blueprint, render_template, request, abort, jsonify
from models.scenePattern import tblscenepattern as tbl
from models.scenes import tblscenes as sc
from extensions import *

from sql import *
from routes._util import campaign_scene_ids, scenes_for_filter, campaigns_for_filter
from remotes import dispatch_led
import led_patterns as reg

sp = Blueprint('sp', __name__)

tblColumns = ['scenePattern_ID', 'scene_ID', 'patternType', 'params', 'orderBy']
primeKey = tblColumns[0]


def _row(r):
    d = r.to_dict()
    d['name'] = reg.display_name(r.patternType)
    return d


@sp.route('/scenePattern')
def edittbl():
    data = select_data_stats()
    volume = currentvolume()
    campaignFilter = appsettingGetCampaignFilter()
    scenes = scenes_for_filter(campaignFilter)
    campaigns = campaigns_for_filter()
    sceneFilter = appsettingGetSceneFilter()
    return render_template('scenePattern_table.html', items=data, volume=volume,
                           scenes=scenes, sceneFilter=int(sceneFilter[0][0]),
                           campaigns=campaigns, campaignFilter=campaignFilter)


@sp.route('/api/led/patterns')
def led_registry():
    """The pattern registry for the editor: types, names, descriptions and
    the ordered field specs each one honors."""
    return jsonify(reg.registry_json())


def _base_query():
    """Rows for the current scene/campaign filter. Unassigned rows (scene 0)
    are ALWAYS included: a new row starts unassigned and must stay visible
    so its scene can be picked from the grid."""
    sceneFilter = appsettingGetSceneFilter()
    campaignFilter = appsettingGetCampaignFilter()
    if int(sceneFilter[0][0]) != 0:
        return tbl.query.filter(db.or_(tbl.scene_ID == int(sceneFilter[0][0]),
                                       tbl.scene_ID == 0))
    if campaignFilter != 0:
        return tbl.query.filter(db.or_(tbl.scene_ID.in_(campaign_scene_ids(campaignFilter)),
                                       tbl.scene_ID == 0))
    return tbl.query


@sp.route('/api/scenePattern')
def data():
    query = _base_query()

    search = request.args.get('search')
    if search:
        querysc = sc.query.filter(db.or_(sc.sceneName.like(f'%{search}%')))
        scene_ids = [rows.scene_ID for rows in querysc.all()]
        query = query.filter(tbl.scene_ID.in_(scene_ids))
    total = query.count()

    order = []
    sort = request.args.get('sort')
    if sort:
        for s in sort.split(','):
            direction = s[0]
            name = s[1:]
            if name not in tblColumns:
                name = primeKey
            col = getattr(tbl, name)
            order.append(col.desc() if direction == '-' else col)
    if not order:
        order = [tbl.scene_ID.asc(), tbl.orderBy.asc()]
    query = query.order_by(*order)

    start = request.args.get('start', type=int, default=-1)
    length = request.args.get('length', type=int, default=-1)
    if start != -1 and length != -1:
        query = query.offset(start).limit(length)

    return {'data': [_row(r) for r in query], 'total': total}


@sp.route('/api/scenePattern', methods=['POST'])
def update():
    """Partial update. Changing patternType without params resets the row to
    that pattern's defaults; params are always validated against the type."""
    data = request.get_json(silent=True) or {}
    if primeKey not in data:
        abort(400)
    row = db.session.get(tbl, int(data[primeKey]))
    if row is None:
        abort(404)
    if 'scene_ID' in data:
        row.scene_ID = int(data['scene_ID'] or 0)
    if 'orderBy' in data:
        try:
            row.orderBy = int(data['orderBy'])
        except (TypeError, ValueError):
            pass
    if 'patternType' in data:
        ptype = str(data['patternType'] or '')
        if not reg.is_type(ptype):
            abort(400)
        row.patternType = ptype
        row.params = json.dumps(reg.coerce(ptype, data.get('params')))
    elif 'params' in data:
        if not reg.is_type(row.patternType):
            abort(400)
        row.params = json.dumps(reg.coerce(row.patternType, data['params']))
    db.session.commit()
    return '', 204


@sp.route('/api/scenepatternaddrow', methods=['POST'])
def scenesaddrow():
    # New rows start unassigned (scene 0) unless the caller names a scene.
    data = request.get_json(silent=True) or {}
    scene_id = int(data.get('scene_ID', 0) or 0)
    last = (db.session.query(db.func.max(tbl.orderBy))
            .filter(tbl.scene_ID == scene_id).scalar())
    order_by = (last or 0) + 1
    CRUD_tblScenePattern([scene_id, 'solid', json.dumps(reg.defaults('solid')),
                          order_by], "C")
    return 'tblScenePattern has a new row'


@sp.route('/api/scenepatterndelrow', methods=['POST'])
def scenesdelrow():
    data = request.get_json(silent=True) or {}
    if primeKey not in data:
        abort(400)
    CRUD_tblScenePattern([data[primeKey]], "D")
    return 'tblScenePattern row ' + str(data[primeKey]) + ' has been deleted'


@sp.route('/api/RPiLEDTest', methods=['POST'])
def RPiLEDTest():
    """Push ONE pattern row to every LED output (this Pi, Remote boxes, the
    relay). The editor may pass unsaved patternType/params to preview them."""
    jdata = request.get_json(silent=True) or {}
    if primeKey not in jdata:
        abort(400)
    row = db.session.get(tbl, int(jdata[primeKey]))
    if row is None:
        abort(404)
    ptype = jdata.get('patternType') or row.patternType
    params = jdata['params'] if 'params' in jdata else row.params
    if not reg.is_type(ptype):
        abort(400)
    dispatch_led(reg.build_payload([(ptype, params)]))
    return '', 204
