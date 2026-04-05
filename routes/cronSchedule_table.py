from flask import Blueprint, render_template, request, abort, jsonify
from extensions import *
from models.cronSchedule import tblcronschedule as tbl
from sql import select_data_stats
from crontab import CronTab

# cid  name          type     notnull  dflt_value  pk
# ---  ------------  -------  -------  ----------  --
# 0    schedule_id   INTEGER  0                    1
# 1    name          TEXT     0                    0
# 2    minute        TEXT     0                    0
# 3    hour          TEXT     0                    0
# 4    day_of_month  TEXT     0                    0
# 5    month         TEXT     0                    0
# 6    day_of_week   TEXT     0                    0
# 7    command       TEXT     0                    0
# 8    description   TEXT     0                    0
# 9    active        INT      0                    0

tblColumns = ['schedule_id', 'name', 'minute', 'hour', 'day_of_month', 'month', 'day_of_week', 'command', 'description', 'active']
primeKey = tblColumns[0]

cs = Blueprint('cs', __name__)


@cs.route('/cronSchedule')
def edittbl():
    data = select_data_stats()
    volume = currentvolume()
    return render_template('cronSchedule_table.html', items=data, volume=volume)


@cs.route('/api/cronSchedule')
def data():
    query = tbl.query.order_by(tbl.name)

    search = request.args.get('search')
    if search:
        query = query.filter(db.or_(
            tbl.name.like(f'%{search}%'),
            tbl.command.like(f'%{search}%'),
            tbl.description.like(f'%{search}%'),
        ))
    total = query.count()

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

    start = request.args.get('start', type=int, default=-1)
    length = request.args.get('length', type=int, default=-1)
    if start != -1 and length != -1:
        query = query.offset(start).limit(length)

    return {
        'data': [row.to_dict() for row in query],
        'total': total,
    }


@cs.route('/api/cronSchedule', methods=['POST'])
def update():
    data = request.get_json()
    if primeKey not in data:
        abort(400)
    row = tbl.query.get(data[primeKey])
    if row is None:
        abort(404)
    for field in tblColumns:
        if field in data:
            setattr(row, field, data[field])
    db.session.commit()
    return '', 204


@cs.route('/api/cronscheduleaddrow', methods=['POST'])
def addrow():
    row = tbl(
        name='New Schedule',
        minute='*',
        hour='*',
        day_of_month='*',
        month='*',
        day_of_week='*',
        command='',
        description='',
        active=0,
    )
    db.session.add(row)
    db.session.commit()
    return jsonify({'schedule_id': row.schedule_id})


@cs.route('/api/cronscheduledelrow', methods=['POST'])
def delrow():
    data = request.get_json()
    if primeKey not in data:
        abort(400)
    row = tbl.query.get(data[primeKey])
    if row is None:
        abort(404)
    db.session.delete(row)
    db.session.commit()
    return f'tblCronSchedule row {data[primeKey]} deleted'


CRON_COMMENT = 'ScenePlay'

@cs.route('/api/applycronschedules', methods=['POST'])
def apply():
    try:
        cron = CronTab(user=True)

        # Remove all previously managed ScenePlay jobs
        for job in list(cron):
            if job.comment.startswith(CRON_COMMENT):
                cron.remove(job)

        # Add all active schedules from the DB
        active_rows = tbl.query.filter_by(active=1).order_by(tbl.name).all()
        for r in active_rows:
            job = cron.new(command=r.command, comment=f'{CRON_COMMENT} {r.name}')
            job.setall(r.minute, r.hour, r.day_of_month, r.month, r.day_of_week)

        cron.write()
        return jsonify({'success': True, 'count': len(active_rows)})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
