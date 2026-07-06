import os
import subprocess

from flask import Blueprint, render_template, request, abort, jsonify
from extensions import *
from models.cronSchedule import tblcronschedule as tbl
from models.scenes import tblscenes
from sql import select_data_stats

# python-crontab needs a real crontab binary — Linux only. On Windows the
# apply step targets Task Scheduler (schtasks) instead; same os.name pattern
# as the players.
if os.name != 'nt':
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
    scenes = tblscenes.query.filter_by(active=1).order_by(tblscenes.sceneName).all()
    return render_template('cronSchedule_table.html', items=data, volume=volume,
                           scenes=scenes)


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
    row = db.session.get(tbl, data[primeKey])
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
    row = db.session.get(tbl, data[primeKey])
    if row is None:
        abort(404)
    db.session.delete(row)
    db.session.commit()
    return f'tblCronSchedule row {data[primeKey]} deleted'


CRON_COMMENT = 'ScenePlay'


_NT_DAYS = ['SUN', 'MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT']   # cron 0=Sunday


def _nt_schtasks_days(day_of_week):
    """Translate a cron day-of-week field into schtasks /d syntax, or None
    when the pattern can't be expressed ('*' -> all days; lists '1,3';
    ranges '1-5'). Steps and names are not supported."""
    dow = (day_of_week or '*').strip()
    if dow == '*':
        return ','.join(_NT_DAYS)
    days = set()
    for part in dow.split(','):
        part = part.strip()
        if '-' in part:
            try:
                lo, hi = (int(x) for x in part.split('-', 1))
            except ValueError:
                return None
            if not (0 <= lo <= hi <= 7):
                return None
            days.update(range(lo, hi + 1))
        elif part.isdigit() and 0 <= int(part) <= 7:
            days.add(int(part))
        else:
            return None
    return ','.join(_NT_DAYS[d % 7] for d in sorted(days)) or None


def _apply_crontab():
    """Install all active schedule rows into the system scheduler. Returns
    (applied, skipped): the user crontab on Linux; Task Scheduler on Windows.
    Shared by the manual Apply button and the wizard's save-and-apply."""
    active_rows = tbl.query.filter_by(active=1).order_by(tbl.name).all()

    if os.name == 'nt':
        # Wipe previously-managed tasks, then create one WEEKLY task per row.
        # schtasks can't express every cron pattern (steps, minute/hour lists,
        # day-of-month/month fields) — inexpressible rows are skipped and
        # counted so the DM sees it rather than silently losing a schedule.
        listing = subprocess.run(['schtasks', '/query', '/fo', 'csv', '/nh'],
                                 capture_output=True, text=True)
        for line in (listing.stdout or '').splitlines():
            name = line.split('","')[0].strip('"').lstrip('\\')
            if name.startswith('ScenePlay_'):
                subprocess.run(['schtasks', '/delete', '/tn', name, '/f'],
                               capture_output=True)
        applied = skipped = 0
        for r in active_rows:
            days = _nt_schtasks_days(r.day_of_week)
            simple_time = ((r.minute or '').strip().isdigit()
                           and (r.hour or '').strip().isdigit())
            wildcard_rest = ((r.day_of_month or '*').strip() == '*'
                             and (r.month or '*').strip() == '*')
            if not (days and simple_time and wildcard_rest):
                skipped += 1
                continue
            safe = ''.join(ch if ch.isalnum() or ch in '-_' else '_' for ch in r.name or 'job')
            proc = subprocess.run(
                ['schtasks', '/create', '/f',
                 '/tn', f'ScenePlay_{safe}_{r.schedule_id}',
                 '/sc', 'WEEKLY', '/d', days,
                 '/st', f'{int(r.hour):02d}:{int(r.minute):02d}',
                 '/tr', r.command],
                capture_output=True, text=True)
            if proc.returncode == 0:
                applied += 1
            else:
                skipped += 1
        return applied, skipped

    cron = CronTab(user=True)
    for job in list(cron):
        if job.comment.startswith(CRON_COMMENT):
            cron.remove(job)
    for r in active_rows:
        job = cron.new(command=r.command, comment=f'{CRON_COMMENT} {r.name}')
        job.setall(r.minute, r.hour, r.day_of_month, r.month, r.day_of_week)
    cron.write()
    return len(active_rows), 0


@cs.route('/api/applycronschedules', methods=['POST'])
def apply():
    try:
        applied, skipped = _apply_crontab()
        return jsonify({'success': True, 'count': applied, 'skipped': skipped})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ── Schedule wizard ─────────────────────────────────────────────────────────────
# Plain-language schedule creation: pick an action, a time and days — the
# server builds the shell command and cron fields, saves the row active, and
# applies the crontab immediately. Raw rows in the table below remain the
# power-user escape hatch (custom commands, exotic cron patterns).

_DAY_NAMES = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']


def _wizard_base_url():
    """The app's own address as seen from a cron job ON this box: always
    localhost, with the port the DM is currently using (8086 in production)."""
    port = request.host.rsplit(':', 1)[1] if ':' in request.host else '80'
    return f'http://localhost:{port}'


def _wizard_command(action, data):
    """Return (command, action_label) for a wizard action, or raise ValueError.

    Commands are generated for THIS server's shell: absolute paths + sh
    quoting for cron on Linux; bare curl (bundled since Win10 1803) + cmd.exe
    quoting for Task Scheduler on Windows."""
    base = _wizard_base_url()
    nt = os.name == 'nt'
    curl = 'curl' if nt else '/usr/bin/curl'
    if action == 'scene':
        scene_id = int(data.get('scene_id', 0) or 0)
        scene = db.session.get(tblscenes, scene_id)
        if not scene:
            raise ValueError('Pick a scene.')
        return (f'{curl} -s -X POST "{base}/activatescenes/?id={scene_id}"',
                f"activate scene '{scene.sceneName}'")
    if action == 'allstop':
        pause = 'timeout /t 2 /nobreak >NUL' if nt else 'sleep 2'
        return (f'{curl} -s -X POST "{base}/killqueue" && {pause} && '
                f'{curl} -s -X POST "{base}/activatescenes/?id=-1"',
                'stop all music and video')
    if action == 'volume':
        vol = int(data.get('volume', -1))
        if not 0 <= vol <= 100:
            raise ValueError('Volume must be 0–100.')
        # JSON body quoting differs: cmd.exe has no single-quoted strings
        body = f'"{{\\"volume\\": {vol}}}"' if nt else f'\'{{"volume": {vol}}}\''
        return (f'{curl} -s -X POST "{base}/set_volume" '
                f'-H "Content-Type: application/json" -d {body}',
                f'set volume to {vol}%')
    if action == 'repeat_on':
        return (f'{curl} -s "{base}/api/keepmusicplaying/on"',
                'turn music repeat ON')
    if action == 'repeat_off':
        return (f'{curl} -s "{base}/api/keepmusicplaying/off"',
                'turn music repeat OFF')
    if action == 'reboot':
        return ('shutdown /r /t 0' if nt else '/usr/bin/sudo /sbin/reboot',
                'restart the computer')
    if action == 'update':
        repo = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
        if nt:
            return (f'cd /d "{repo}" && git stash && git pull && shutdown /r /t 0',
                    'update ScenePlay (git pull) and restart')
        return (f'cd "{repo}" && /usr/bin/git stash && /usr/bin/git pull && '
                f'/usr/bin/sudo /sbin/reboot',
                'update ScenePlay (git pull) and restart')
    raise ValueError(f'Unknown action {action!r}')


def _wizard_schedule(data):
    """Return (minute, hour, day_of_week, when_label) from the wizard's
    time + days-of-week (0=Sunday … 6=Saturday, cron convention)."""
    t = (data.get('time') or '').strip()
    try:
        hour, minute = t.split(':')
        hour, minute = int(hour), int(minute)
        assert 0 <= hour <= 23 and 0 <= minute <= 59
    except (ValueError, AssertionError):
        raise ValueError('Pick a valid time.')
    days = sorted({int(d) for d in (data.get('days') or []) if 0 <= int(d) <= 6})
    if not days:
        raise ValueError('Pick at least one day.')
    if len(days) == 7:
        dow, when_days = '*', 'every day'
    elif days == [1, 2, 3, 4, 5]:
        dow, when_days = '1-5', 'on weekdays'
    elif days == [0, 6]:
        dow, when_days = '0,6', 'on weekends'
    else:
        dow = ','.join(str(d) for d in days)
        when_days = 'on ' + ', '.join(_DAY_NAMES[d] for d in days)
    ampm = ('12' if hour % 12 == 0 else str(hour % 12)) + f':{minute:02d} ' + ('PM' if hour >= 12 else 'AM')
    return str(minute), str(hour), dow, f'{when_days} at {ampm}'


@cs.route('/api/cronwizard', methods=['POST'])
def cron_wizard():
    data = request.get_json() or {}
    try:
        command, action_label = _wizard_command(data.get('action', ''), data)
        minute, hour, dow, when_label = _wizard_schedule(data)
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400

    description = f'{when_label}: {action_label}'
    name = (data.get('name') or '').strip() or description[:60]
    row = tbl(name=name, minute=minute, hour=hour, day_of_month='*', month='*',
              day_of_week=dow, command=command, description=description, active=1)
    db.session.add(row)
    db.session.commit()
    try:
        count, _skipped = _apply_crontab()
    except Exception as e:
        # row saved but scheduler not written (e.g. no crontab binary) — surface it
        return jsonify({'success': False, 'schedule_id': row.schedule_id,
                        'error': f'Saved, but applying the schedule failed: {e}'}), 500
    return jsonify({'success': True, 'schedule_id': row.schedule_id,
                    'description': description, 'applied': count})
