from flask import Blueprint, render_template, request, abort, jsonify, json, redirect, url_for
from extensions import *

from models.music import tblmusic as tbl
from models.mediaMetadata import tblmediametadata as metaTbl

from sql import *
import alsaaudio

mu = Blueprint('mu', __name__)

tblColumns = ['song_ID', 'path', 'song', 'pTimes', 'playedDTTM', 'active', 'genre','que', 'urlSource', 'dnLoadStatus', 'videoId', 'displayName', 'metaStatus']
primeKey = tblColumns[0]

# Default listing/search key: the human name once metadata fills it, else the
# <videoId>.<ext> filename. Filenames are opaque IDs now, so sorting/searching by
# `song` alone would be useless.
_name_key = db.func.coalesce(db.func.nullif(tbl.displayName, ''), tbl.song)

# Soft FK into tblMediaMetadata (see models/mediaMetadata.py). Only needed when
# sorting by a metadata column — row values are merged after pagination instead.
_meta_join = db.and_(metaTbl.media_type == 'music', metaTbl.media_id == tbl.song_id)
_meta_sort = {'duration': metaTbl.duration, 'uploader': metaTbl.uploader}

@mu.route('/music')
def edittbl():
    data = select_data_stats()
    volume = currentvolume()
    return render_template('musicMedia_table.html',items=data,volume=volume)


@mu.route('/api/music')
def data():
    query = tbl.query
    search = request.args.get('search')

    if search:
        query = query.filter(db.or_(
            tbl.song.like(f'%{search}%'),
            tbl.displayName.like(f'%{search}%')
        ))
    total = query.count()

    # sorting (applied on top of the search filter; falls back to _name_key)
    sort = request.args.get('sort')
    order = []
    if sort:
        joined = False
        for s in sort.split(','):
            direction = s[0]
            name = s[1:]
            if name in _meta_sort:
                if not joined:
                    query = query.outerjoin(metaTbl, _meta_join)
                    joined = True
                col = _meta_sort[name]
            else:
                if name not in tblColumns:
                    name = primeKey
                col = getattr(tbl, name)
            if direction == '-':
                col = col.desc()
            order.append(col)
    query = query.order_by(*order) if order else query.order_by(_name_key)

    # pagination
    start = request.args.get('start', type=int, default=-1)
    length = request.args.get('length', type=int, default=-1)
    if start != -1 and length != -1:
        query = query.offset(start).limit(length)

    # response — graft the promoted metadata columns onto each row (one batched
    # lookup for the page, not a query per row)
    rows = query.all()
    ids = [r.song_id for r in rows]
    meta = {m.media_id: m for m in metaTbl.query.filter(
        metaTbl.media_type == 'music', metaTbl.media_id.in_(ids))} if ids else {}
    data = []
    for r in rows:
        d = r.to_dict()
        m = meta.get(r.song_id)
        d['duration']  = m.duration  if m else None
        d['uploader']  = m.uploader  if m else None
        d['thumbnail'] = m.thumbnail if m else None
        data.append(d)
    return {
        'data': data,
        'total': total,
    }


@mu.route('/api/music', methods=['POST'])
def update():
    data = request.get_json()
    #print(f"{data}") # data)
    if primeKey not in data:
        abort(400)
    TSP = db.session.get(tbl, data[primeKey]) # data[primeKey])
    # videoId is the dedup identity and metaStatus the metadata-queue state —
    # machine-managed. They sit in tblColumns for display/sort only; a client
    # POSTing them would corrupt dedup or wedge the queue.
    for field in tblColumns:
        if field in ('videoId', 'metaStatus'):
            continue
        if field in data:
            setattr(TSP, field, data[field])
            if str(field) == 'dnLoadStatus' and int(data['dnLoadStatus']) == 1:
                appsettingYT_QuePlayFlagUpdate(1)
                # Re-queuing a download also retries metadata that never landed
                # or failed out — the manual "try again" path (self-guarded).
                requeue_metadata_if_missing('music', data[primeKey])
            if str(field) == 'que' and int(data['que']) == 1:
                appsettingAudioPlayFlagUpdate(1)
            
    db.session.commit()
    return '', 204

@mu.route('/api/musicaddrow', methods=['POST'])
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
    # "Remove entirely": with video-id dedup one row/file is shared across scenes,
    # so this drops the scene-links, the metadata row, the DB row AND the on-disk
    # file together (see sql.delete_media_row). Removing from a single scene is a
    # scene-LINK delete, done from the scene editor, not here.
    links = delete_media_row('music', data[primeKey])
    return jsonify({'deleted': data[primeKey], 'scene_links_removed': links})