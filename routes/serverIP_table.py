from flask import Blueprint, render_template, request, abort, jsonify, json, redirect, url_for
from extensions import *

from models.serverIP import tblserversip as tbl
from sql import *
import alsaaudio

# cid  name          type     notnull  dflt_value  pk
# ---  ------------  -------  -------  ----------  --
# 0    ServerIP_ID   INTEGER  0                    1 
# 1    serverName    TEXT     0                    0 
# 2    ipAddress     TEXT     0                    0 
# 3    ports         TEXT     0                    0 
# 4    active        INT      0                    0 
# 5    PingTime      TEXT     0                    0 
# 6    serverroleid  INT      0                    0 

ip = Blueprint('ip', __name__)

tblColumns = ['ServerIP_ID', 'serverName', 'ipAddress', 'ports','active','PingTime','serverroleid']
primeKey = tblColumns[0]
@ip.route('/serverIP')
def edittbl():
    data = select_data_stats()#arr)
    mixer = alsaaudio.Mixer("Master")
    volume = mixer.getvolume()[0]
    return render_template('serverIP_table.html',items=data,volume=volume)

@ip.route('/api/serverIP')
def data():
    query = tbl.query.order_by(tbl.serverName)

    # search filter
    search = request.args.get('search')
    if search:
        query = query.filter(db.or_(
            tbl.serverName.like(f'%{search}%'),
            tbl.ports.like(f'%{search}%'),
            tbl.ipAddress.like(f'%{search}%')
            
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

@ip.route('/api/serverIP', methods=['POST'])
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


@ip.route('/api/serveripaddrow', methods=['POST'])
def scenesaddrow():
    row = [' ', '127.0.0.1', '',1,1]
    CRUD_tblServersIP(row,"C")
    return 'tblserverip has a new row'

@ip.route('/api/serveripdelrow', methods=['POST'])
def scenesdelrow():
    data = request.get_json()
    #print(data)
    if primeKey not in data:
        abort(400)
    row = [data[primeKey]]
    CRUD_tblServersIP(row,"D")
    return 'tblserverip row ' + data[primeKey] + ' has been deleted'


