from flask import Blueprint, render_template, request, abort, jsonify, json, redirect, url_for
from extensions import db
from extensions2 import *
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
    mixer = alsaaudio.Mixer("Master")
    volume = mixer.getvolume()[0]
    return render_template('campaign_table.html',volume=volume)

@cp.route('/api/campaigns')
def data():
    query = tbl.query
    return {
        'data': [tbl.to_dict() for tbl in query]
    }

