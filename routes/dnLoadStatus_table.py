from flask import Blueprint, render_template, request, abort, jsonify, json, redirect, url_for
from extensions import db
from extensions2 import *
import alsaaudio
from models.status import lutstatus as tbl
from sql import *


# cid  name       type     notnull  dflt_value  pk
# ---  ---------  -------  -------  ----------  --
# 0    genre_id   INTEGER  0                    1 
# 1    genre      TEXT     0                    0 
# 2    directory  TEXT     0                    0 
# 3    active     INTEGER  0                    0 
# 4    orderBY    INTEGER  0                    0

tblColumns = ['pkey', 'status_ID', 'status']
primeKey = tblColumns[0]


dls = Blueprint('dls', __name__)


@dls.route('/genre')
def edittbl():
    data = select_data_stats()
    mixer = alsaaudio.Mixer("Master")
    volume = mixer.getvolume()[0]
    return render_template('genre_table.html',items=data,volume=volume)

@dls.route('/api/dnLoadStatus')
def data():
    query = tbl.query.order_by(tbl.status_ID)
    return {
        'data': [tbl.to_dict() for tbl in query]
    }

