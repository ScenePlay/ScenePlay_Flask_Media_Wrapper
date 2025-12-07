from flask import Blueprint, render_template, request, abort, jsonify, json, redirect, url_for
from extensions import *

from models.videoMedia import tblvideomedia as tbl
from sql import *
import alsaaudio

    #   // cid  name          type     notnull  dflt_value  pk
    #   // ---  ------------  -------  -------  ----------  --
    #   // 0    video_ID      INTEGER  0                    1 
    #   // 1    path          TEXT     0                    0 
    #   // 2    title         TEXT     0                    0 
    #   // 3    pTimes        INT      0                    0 
    #   // 4    playedDTTM    TEXT     0                    0 
    #   // 5    active        INT      0                    0 
    #   // 6    genre         INT      0                    0 
    #   // 7    que           INT      0                    0 
    #   // 8    urlSource     TEXT     0                    0 
    #   // 9    dnLoadStatus  INT      0                    0 


vm = Blueprint('vm', __name__)

tblColumns = ['video_ID', 'path', 'title', 'pTimes', 'playedDTTM', 'active', 'genre','que', 'urlSource', 'dnLoadStatus']
primeKey = tblColumns[0]

@vm.route('/videomedia')
def edittbl():
    data = select_data_stats()
    volume = currentvolume()
    return render_template('videoMedia_table.html',items=data,volume=volume)


@vm.route('/api/videomedia')
def data():
    query = tbl.query.order_by(tbl.title)
    search = request.args.get('search')

    if search:
        query = tbl.query.filter(db.or_(
            tbl.title.like(f'%{search}%')
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
    

@vm.route('/api/videomedia', methods=['POST'])
def update():
    data = request.get_json()
    #print(data)
    if primeKey not in data:
        abort(400)
    TSP = tbl.query.get(data[primeKey])
    for field in tblColumns:
        if field in data:
            setattr(TSP, field, data[field])
            if str(field) == 'dnLoadStatus' and int(data['dnLoadStatus']) == 1:
                appsettingYT_QuePlayFlagUpdate(1)
            if str(field) == 'que' and int(data['que']) == 1:
                appsettingVideoPlayFlagUpdate(1)
    db.session.commit()

    return '', 204

@vm.route('/api/videomediaaddrow', methods=['POST'])
def videomediaaddrow():
    row = ['empty','empty',0,'',1,1,0,'','']
    CRUD_tblvideomedia(row,"C")
    return 'tblvideomedia has a new row'

@vm.route('/api/videomediadelrow', methods=['POST'])
def videomediadelrow():
    data = request.get_json()
    #print(data)
    if primeKey not in data:
        abort(400)
    row = [data[primeKey]]
    CRUD_tblvideomedia(row,"D")
    return 'tblvideomedia row ' + data['song_id'] + ' has been deleted'