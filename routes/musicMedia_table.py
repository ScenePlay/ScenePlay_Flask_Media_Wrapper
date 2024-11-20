from flask import Blueprint, render_template, request, abort, jsonify, json, redirect, url_for
from extensions import db
from extensions2 import *
from models.music import tblmusic as tbl

from sql import *
import alsaaudio

mu = Blueprint('mu', __name__)

tblColumns = ['song_ID', 'path', 'song', 'pTimes', 'playedDTTM', 'active', 'genre','que', 'urlSource', 'dnLoadStatus']
primeKey = tblColumns[0]
@mu.route('/music')
def edittbl():
    data = select_data_stats()
    mixer = alsaaudio.Mixer("Master")
    volume = mixer.getvolume()[0]
    return render_template('musicMedia_table.html',items=data,volume=volume)


@mu.route('/api/music')
def data():
    query = tbl.query.order_by(tbl.song)
    search = request.args.get('search')
    
    if search:
        query = tbl.query.filter(db.or_(
            tbl.song.like(f'%{search}%')
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


@mu.route('/api/music', methods=['POST'])
def update():
    data = request.get_json()
    #print(f"{data}") # data)
    if primeKey not in data:
        abort(400)
    TSP = tbl.query.get(data[primeKey]) # data[primeKey])
    for field in tblColumns:
        if field in data:
            setattr(TSP, field, data[field])
            if str(field) == 'dnLoadStatus' and int(data['dnLoadStatus']) == 1:
                appsettingYT_QuePlayFlagUpdate(1)            
            if str(field) == 'que' and int(data['que']) == 1:
                appsettingAudioPlayFlagUpdate(1)
            
    db.session.commit()
    return '', 204

@mu.route('/api/musicaddrow')
def musicaddrow():
    row = [' ',' ',0,'',1,1,0,'','']
    CRUD_tblMusic(row,"C")
    return 'tblmusic has a new row'

@mu.route('/api/musicdelrow', methods=['POST'])
def musicdelrow():
    data = request.get_json()
    #print(data)
    if primeKey not in data:
        abort(400)
    row = [data[primeKey]]
    CRUD_tblMusic(row,"D")
    return 'tblmusic row ' + data[primeKey] + ' has been deleted'