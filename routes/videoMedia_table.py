from flask import Blueprint, render_template, request, abort, jsonify, json, redirect, url_for
from extensions import *

from models.videoMedia import tblvideomedia as tbl
from models.mediaMetadata import tblmediametadata as metaTbl
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

tblColumns = ['video_ID', 'path', 'title', 'pTimes', 'playedDTTM', 'active', 'genre','que', 'urlSource', 'dnLoadStatus', 'videoId', 'displayName', 'metaStatus']
primeKey = tblColumns[0]

# Human name once metadata fills it, else the <videoId>.<ext> filename.
_name_key = db.func.coalesce(db.func.nullif(tbl.displayName, ''), tbl.title)

# Soft FK into tblMediaMetadata — join only for metadata-column sorts; row
# values are merged after pagination (see music route).
_meta_join = db.and_(metaTbl.media_type == 'video', metaTbl.media_id == tbl.video_id)
_meta_sort = {'duration': metaTbl.duration, 'uploader': metaTbl.uploader}

@vm.route('/videomedia')
def edittbl():
    data = select_data_stats()
    volume = currentvolume()
    return render_template('videoMedia_table.html',items=data,volume=volume)


@vm.route('/api/videomedia')
def data():
    query = tbl.query
    search = request.args.get('search')

    if search:
        query = query.filter(db.or_(
            tbl.title.like(f'%{search}%'),
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
    ids = [r.video_id for r in rows]
    meta = {m.media_id: m for m in metaTbl.query.filter(
        metaTbl.media_type == 'video', metaTbl.media_id.in_(ids))} if ids else {}
    data = []
    for r in rows:
        d = r.to_dict()
        m = meta.get(r.video_id)
        d['duration']  = m.duration  if m else None
        d['uploader']  = m.uploader  if m else None
        d['thumbnail'] = m.thumbnail if m else None
        data.append(d)
    return {
        'data': data,
        'total': total,
    }
    

@vm.route('/api/videomedia', methods=['POST'])
def update():
    data = request.get_json()
    #print(data)
    if primeKey not in data:
        abort(400)
    TSP = db.session.get(tbl, data[primeKey])
    # videoId / metaStatus are machine-managed (dedup identity, queue state) —
    # display/sort only, never client-writable (see music route).
    for field in tblColumns:
        if field in ('videoId', 'metaStatus'):
            continue
        if field in data:
            setattr(TSP, field, data[field])
            if str(field) == 'dnLoadStatus' and int(data['dnLoadStatus']) == 1:
                appsettingYT_QuePlayFlagUpdate(1)
                # Re-queuing a download also retries metadata that never landed
                # or failed out — the manual "try again" path (self-guarded).
                requeue_metadata_if_missing('video', data[primeKey])
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
    # Remove entirely: scene-links + metadata + row + on-disk file (see music route).
    links = delete_media_row('video', data[primeKey])
    return jsonify({'deleted': data[primeKey], 'scene_links_removed': links})