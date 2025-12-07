from flask import Blueprint, render_template, request, abort, jsonify, json, redirect, url_for
from extensions import *

from models.serverRole import tblserverrole as tbl
from sql import *
import alsaaudio

# 0|ID|INTEGER|0||1
# 1|name|TEXT|0||0
# 2|active|INT|0||0
# 3|orderBy|INT|0||0


sr = Blueprint('sr', __name__)

tblColumns = ['ID', 'name', 'active', 'orderBy']
primeKey = tblColumns[0]

@sr.route('/serverrole')
def edittbl():
    data = select_data_stats()#arr)
    volume = currentvolume()
    return render_template('serverrole_table.html',items=data,volume=volume)

@sr.route('/api/serverrole')
def data():
    query = tbl.query.order_by(tbl.name)


    # search filter
    search = request.args.get('search')
    if search:
        query = query.filter(db.or_(
            tbl.name.like(f'%{search}%')
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
            query = query.order_by(*order)

    # pagination
    start = request.args.get('start', type=int, default=-1)
    length = request.args.get('length', type=int, default=-1)
    if start != -1 and length != -1:
        query = tbl.query.offset(start).limit(length)

    # response
    return {
        'data': [tbl.to_dict() for tbl in query],
        'total': total,
    }

@sr.route('/api/serverrole', methods=['POST'])
def update():
    data = request.get_json()
    #print(data)
    if primeKey not in data:
        abort(400)
    TSP = tbl.query.get(data[primeKey])
    for field in ['name']:
        if field in data:
            setattr(TSP, field, data[field])
    db.session.commit()
    return '', 204

@sr.route('/api/serverroleaddrow')
def serverroleaddrow():
    row = ['new', 1,1]
    CRUD_tblServerRole(row,"C")
    return 'tblserverrole has a new row'

@sr.route('/api/serverroledelrow', methods=['POST'])
def serverroledelrow():
    data = request.get_json()
    #print(data)
    if primeKey not in data:
        abort(400)
    row = [data[primeKey]]
    CRUD_tblServerRole(row,"D")
    return 'tblserverrole row ' + data[primeKey] + ' has been deleted'
