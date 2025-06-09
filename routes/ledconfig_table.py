from flask import Blueprint, render_template, request, abort, jsonify, json, redirect, url_for
from extensions import *

from sql import *
import alsaaudio
from models.ledConfig import tblledconfig as tbl




# cid  name          type     notnull  dflt_value  pk
# ---  ------------  -------  -------  ----------  --
# 0    ledConfig_ID  INTEGER  0                    1 
# 1    pin           INT      0                    0 
# 2    ledCount      INT      0                    0 
# 3    brightness    REAL     0                    0 
# 4    active        INT      0                    0 



lcf = Blueprint('lcf', __name__)

tblColumns = ['ledConfig_ID','pin', 'ledCount', 'brightness', 'active']
primeKey = tblColumns[0]

@lcf.route('/api/ledconfigmodel')
def datalcf():
    query = tbl.query.order_by(tbl.pin)
    return {
        'data': [tbl.to_dict() for tbl in query]
    }
    
@lcf.route('/ledconfig')
def edittbl():
    data = select_data_stats()
    mixer = alsaaudio.Mixer("Master")
    volume = mixer.getvolume()[0]
    return render_template('ledConfig_table.html',items=data,volume=volume)


@lcf.route('/api/ledconfig')
def data():
    query = tbl.query.order_by(tbl.ledConfig_ID)

    search = request.args.get('search')
    
    if search:
        query = query.filter(db.or_(
            tbl.modelName.like(f'%{search}%')
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
    

@lcf.route('/api/ledconfigsave', methods=['POST'])
def update():
    data = request.get_json()
    print(data)
    if primeKey not in data:
        abort(400)
    TSP = tbl.query.get(data[primeKey])
    for field in tblColumns:
        if field in data:
            setattr(TSP, field, data[field])
    db.session.commit()
    return '', 204


# @lcf.route('/api/ledtypemodeladdrow')
# def ledtypemodeladdrow():
#     row = [' ','{"type": "solid","color": [0,0,0]}']
#     CRUD_tblLEDTypeModel(row,"C")
#     return 'tblledtypemodel has a new row'


# @lcf.route('/api/ledtypemodeldelrow', methods=['POST'])
# def ledtypemodeldelrow():
#     data = request.get_json()
#     print(data)
#     if primeKey not in data:
#         abort(400)
#     row = [data[primeKey]]
#     CRUD_tblLEDTypeModel(row,"D")
#     return 'tblledtypemodel row ' + data[primeKey] + ' has been deleted'