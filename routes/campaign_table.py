from flask import Blueprint, render_template, request, abort, jsonify, json, redirect, url_for
from extensions import *

import alsaaudio
from models.campaigns import tblcampaigns as tbl
from sql import *

cp = Blueprint('cp', __name__)

# cid  name           type     notnull  dflt_value  pk
# ---  -------------  -------  -------  ----------  --
# 0    campaign_id    INTEGER  1                    1 
# 1    campaign_name  TEXT     0                    0 
# 2    active         INT      0                    0 
# 3    order_by       TEXT     0                    0 

tblColumns = ['campaign_id', 'campaign_name', 'active', 'order_by']
primeKey = tblColumns[0]
@cp.route('/campaigns')
def edittbl():
    data = select_data_stats()#arr)
    mixer = alsaaudio.Mixer("Master")
    volume = mixer.getvolume()[0]
    return render_template('campaigns_table.html',items=data,volume=volume)

@cp.route('/api/campaigns')
def data():
    query = tbl.query.order_by(tbl.campaign_name)
    
    # search filter
    search = request.args.get('search')
    if search:
        query = query.filter(db.or_(
            tbl.campaign_name.like(f'%{search}%')
        ))
    total = query.count()
    
    #sorting
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
    
    
    return {
        'data': [tbl.to_dict() for tbl in query],
        'total': total,
    }

@cp.route('/api/campaigns', methods=['POST'])
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


@cp.route('/api/campaignaddrow', methods=['POST'])
def campaignaddrow():
    newrow = tbl( campaign_name=' ', active=1, order_by='10')
    db.session.add(newrow)
    db.session.commit()
    return 'tblCampaign has a new row'


@cp.route('/api/campaigndelrow', methods=['POST'])
def campaigndelrow():
    data = request.get_json()
    if primeKey not in data:
        abort(400)
    TSP = tbl.query.get(data[primeKey])
    db.session.delete(TSP)
    db.session.commit()  
    return 'tblCampaign row ' + data[primeKey] + ' has been deleted'

@cp.route('/api/campaignSelect', methods=['POST'])
def updateCampaignSelect():
    data = request.get_json()
    appsettingSetCampaignSelected(int(data['campaign_id']))
    return '', 204


@cp.route('/api/getcampaignSelect', methods=['GET'])
def updateGetCampaignSelect():
    data = appsettingGetCampaignSelected()
    return jsonify(CampaignID=int(data[0][0]))
