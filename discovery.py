"""LAN discovery for ScenePlay and WLED devices.

Replaces the old ICMP-ping fan-out (ipsearch.py / ippinger.py / the shell
launchers), which forked four Python processes, ping'd every host, ran a dozen
sequential 1s port checks with a 2s sleep between hosts, and recorded ANY box
with a common port open (SSH boxes, printers, the gateway...) — minutes per /24
and brutal on a Raspberry Pi Zero 2W.

This does a concurrent TCP-connect sweep (one process, thread pool) and then
*asks* each responder what it is:

  * ScenePlay port open  -> GET /api/server-info ; keep if app == "ScenePlay"
  * port 80 open         -> GET /json/info       ; keep if it looks like WLED
  * obs-websocket open   -> read the Hello frame ; keep if it names a version

Only devices that identify themselves are written to tblServersIP, so the table
stops filling up with unrelated hardware. A /24 finishes in a few seconds even
on a Pi Zero 2W.

Public API:
    scan_and_record(app)  -> summary dict (runs the whole pipeline, blocking)
    start_scan(app)       -> bool (launches scan_and_record in a daemon thread;
                             returns False if a scan is already running)
"""

import ipaddress
import json
import socket
import threading
import concurrent.futures

import requests

from extensions import db
from models.serverIP import tblserversip as ServerIP
from models.serverRole import tblserverrole as ServerRole


# Ports we probe. Keeping this list tiny is what makes the sweep fast; every
# extra port multiplies the number of connect attempts across the whole /24.
SCENEPLAY_PORT = 8086
WLED_PORT      = 80
OBS_PORT       = 4455    # obs-websocket v5 default (the streaming rig's control port)

# A live host normally answers in milliseconds, but under a burst of hundreds of
# concurrent connects some SYN packets get dropped (switch buffers, WiFi, the
# target's backlog). The Linux kernel retransmits a dropped SYN after ~1s, so the
# timeout must sit ABOVE that — at 0.5s a single dropped SYN silently loses a real
# device (this is what made a WiFi Pi Zero flicker in and out of results).
CONNECT_TIMEOUT = 1.2
HTTP_TIMEOUT    = 2.0    # per-device identify request
MAX_WORKERS     = 50     # thread pool size; modest so a Pi Zero 2W stays responsive
# One pass is reliable once the timeout clears the ~1s SYN retransmit (measured
# 0 misses at 1.2s). `sweep(rounds=N)` re-probes still-closed pairs and unions the
# hits for pathologically lossy WiFi, at ~+12s/round — bump it there, not here.
SWEEP_ROUNDS    = 1

# One scan at a time. The trigger is a UI button that a user can double-click;
# without this a second press would stack another full sweep on top of the first.
_scan_lock = threading.Lock()

# Progress for the UI status bar (Servers page). The sweep/identify loops bump
# `done` as their futures complete; GET /api/pingnetwork/status polls this.
# Plain dict mutation — single writer thread, readers only copy.
_progress = {'state': 'idle', 'done': 0, 'total': 0, 'summary': None}


def get_progress():
    return dict(_progress)


def check_port(ip, port, timeout=CONNECT_TIMEOUT):
    """True if a TCP connect to (ip, port) succeeds within the timeout."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            return s.connect_ex((str(ip), port)) == 0
    except OSError:
        return False


def get_local_ip():
    """This machine's LAN IP (the interface that would reach the network),
    or '127.0.0.1' if we can't tell."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('10.255.255.255', 1))   # non-routable; no packets are sent
        return s.getsockname()[0]
    except OSError:
        return '127.0.0.1'
    finally:
        s.close()


def sweep(ports=(SCENEPLAY_PORT, WLED_PORT, OBS_PORT), rounds=SWEEP_ROUNDS):
    """Concurrent TCP-connect sweep of the local /24.

    Returns {ip_str: set(open_ports)} for every host with at least one of the
    probed ports open. Skips our own address.

    Runs up to `rounds` passes, re-probing only the (host, port) pairs not yet
    confirmed open and unioning the hits. A live device dropped from one pass by
    transient packet loss is picked up by the next; already-found pairs are never
    re-probed, so the extra rounds only re-scan quiet addresses."""
    local_ip = get_local_ip()
    if local_ip == '127.0.0.1':
        return {}, local_ip

    network = ipaddress.ip_network(
        '.'.join(local_ip.split('.')[:-1]) + '.0/24', strict=False)
    targets = [str(h) for h in network.hosts() if str(h) != local_ip]

    open_ports = {}
    for _ in range(max(1, rounds)):
        pending = [(h, p) for h in targets for p in ports
                   if p not in open_ports.get(h, ())]
        if not pending:
            break
        _progress.update(state='sweeping', done=0, total=len(pending))
        with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
            futures = {ex.submit(check_port, h, p): (h, p) for (h, p) in pending}
            for fut in concurrent.futures.as_completed(futures):
                host_s, port = futures[fut]
                _progress['done'] += 1
                try:
                    if fut.result():
                        open_ports.setdefault(host_s, set()).add(port)
                except Exception:
                    pass
    return open_ports, local_ip


def _identify_sceneplay(ip):
    """Return a ScenePlay device dict if this host is a ScenePlay server, else None."""
    try:
        r = requests.get(f'http://{ip}:{SCENEPLAY_PORT}/api/server-info',
                         timeout=HTTP_TIMEOUT)
        info = r.json()
    except (requests.RequestException, ValueError):
        return None
    if not isinstance(info, dict) or info.get('app') != 'ScenePlay':
        return None
    caps = info.get('capabilities') or {}
    return {
        'kind':    'sceneplay',
        'ip':      ip,
        'name':    (info.get('server_name') or '').strip() or ip,
        'version': (info.get('version') or '').strip(),
        'is_led':  bool(caps.get('led')),
    }


def _identify_wled(ip):
    """Return a WLED device dict if this host is a WLED controller, else None."""
    try:
        r = requests.get(f'http://{ip}:{WLED_PORT}/json/info', timeout=HTTP_TIMEOUT)
        info = r.json()
    except (requests.RequestException, ValueError):
        return None
    # WLED's /json/info always carries an LED block and a firmware version.
    if not isinstance(info, dict) or 'leds' not in info or 'ver' not in info:
        return None
    return {
        'kind':    'wled',
        'ip':      ip,
        'name':    (info.get('name') or '').strip() or ip,
        'version': str(info.get('ver') or '').strip(),
    }


def _identify_obs(ip):
    """Return an OBS device dict if this host runs obs-websocket, else None.

    obs-websocket v5 sends its Hello (op 0) the instant the WebSocket opens —
    BEFORE authentication — and that frame names the server version. So we can
    identify OBS, and read its version, without ever knowing the password. A
    wrong service on 4455 fails the WebSocket handshake or the JSON parse and
    is dropped; a password-protected OBS still says Hello, so it is found."""
    try:
        import websocket
    except ImportError:
        return None
    ws = None
    try:
        ws = websocket.create_connection(f'ws://{ip}:{OBS_PORT}',
                                         timeout=HTTP_TIMEOUT)
        hello = json.loads(ws.recv())
    except Exception:
        return None
    finally:
        if ws is not None:
            try:
                ws.close()
            except Exception:
                pass
    if not isinstance(hello, dict) or hello.get('op') != 0:
        return None
    d = hello.get('d') or {}
    ver = str(d.get('obsWebSocketVersion') or '').strip()
    if not ver:
        return None
    return {
        'kind':    'obs',
        'ip':      ip,
        'name':    'OBS Studio',
        'version': ver,
        'locked':  bool(d.get('authentication')),   # password set on OBS
    }


def identify(open_ports):
    """Probe each swept host to decide what it is. Returns a list of device dicts
    (only ScenePlay and WLED responders survive)."""
    devices = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = {}
        for ip, ports in open_ports.items():
            if SCENEPLAY_PORT in ports:
                futures[ex.submit(_identify_sceneplay, ip)] = ip
            if WLED_PORT in ports:
                futures[ex.submit(_identify_wled, ip)] = ip
            if OBS_PORT in ports:
                futures[ex.submit(_identify_obs, ip)] = ip
        _progress.update(state='identifying', done=0, total=len(futures))
        for fut in concurrent.futures.as_completed(futures):
            _progress['done'] += 1
            try:
                dev = fut.result()
            except Exception:
                dev = None
            if dev:
                devices.append(dev)
    return devices


def _role_id(name):
    role = ServerRole.query.filter(ServerRole.name == name).first()
    return role.ID if role else None


def _ensure_role(name, order_by):
    """Role id for `name`, creating the role if it is missing. Fresh installs
    seed the roles (tblServerRole.json); this backfills a DB that predates a
    role — the OBS label — so the feature works without a migration."""
    role = ServerRole.query.filter(ServerRole.name == name).first()
    if role is None:
        role = ServerRole(name=name, active=1, orderBy=order_by)
        db.session.add(role)
        db.session.flush()          # assign role.ID inside this transaction
    return role.ID


def _record(devices, open_ports):
    """Upsert identified devices into tblServersIP (matched by ipAddress).

    Never deletes or deactivates rows we didn't see — the schema can't tell a
    hand-entered row from a discovered one, so a device that's merely off this
    time just keeps its old PingTime.

    One host can answer for more than one thing (the streaming rig commonly
    runs ScenePlay AND OBS), so devices are merged per ip into a single row —
    its ports column already lists every open port.

    Role rules:
      * a WLED or OBS-only responder adopts the matching role, but only when the
        row has no meaningful role yet (new, NULL, or the placeholder "None"
        role), so a manual choice always stands. A box that is also a ScenePlay
        server keeps its ScenePlay role — the 4455 in its ports column is what
        shows it runs OBS;
      * serverroleid is NEVER left NULL — every row lands on at least the "None"
        role. A NULL there crashes the serverIP grid (it does
        `serverroleid.toString()`), which is exactly what broke the display."""
    from routes._util import _now

    wled_role = _role_id('WLED')
    none_role = _role_id('None')
    # Only spend a write to create the OBS role when we actually found OBS.
    obs_role  = (_ensure_role('OBS', 50)
                 if any(d['kind'] == 'obs' for d in devices) else None)

    by_ip = {}
    for dev in devices:
        by_ip.setdefault(dev['ip'], []).append(dev)

    created = updated = 0
    for ip, devs in by_ip.items():
        kinds = {d['kind'] for d in devs}
        ports_str = ', '.join(str(p) for p in sorted(open_ports.get(ip, [])))
        row = ServerIP.query.filter(ServerIP.ipAddress == ip).first()
        if row is None:
            row = ServerIP(ipAddress=ip)
            db.session.add(row)
            created += 1
        else:
            updated += 1

        # ScenePlay and WLED report a real name; OBS does not. Name from a
        # named responder when there is one; otherwise call an OBS-only box
        # "OBS Studio", but never clobber a name already on the row.
        named = next((d for d in devs if d['kind'] in ('sceneplay', 'wled')),
                     None)
        if named:
            row.serverName = named['name']
            row.version    = named.get('version') or None
        elif 'obs' in kinds:
            if not (row.serverName or '').strip():
                row.serverName = 'OBS Studio'
            obs_ver = next((d.get('version') for d in devs
                            if d['kind'] == 'obs'), None)
            row.version = obs_ver or row.version

        row.ports    = ports_str
        row.active   = 1
        row.PingTime = _now()

        role_unset = row.serverroleid in (None, none_role)
        if role_unset and 'wled' in kinds and wled_role:
            row.serverroleid = wled_role
        elif (role_unset and 'obs' in kinds and obs_role
              and 'sceneplay' not in kinds):
            row.serverroleid = obs_role
        if row.serverroleid is None and none_role is not None:
            row.serverroleid = none_role
    db.session.commit()
    return created, updated


def scan_and_record(app):
    """Full pipeline: sweep -> identify -> record. Blocking; returns a summary."""
    with _scan_lock:
        open_ports, local_ip = sweep()
        with app.app_context():
            devices = identify(open_ports)
            created, updated = _record(devices, open_ports)
        summary = {
            'local_ip':    local_ip,
            'hosts_open':  len(open_ports),
            'sceneplay':   sum(1 for d in devices if d['kind'] == 'sceneplay'),
            'wled':        sum(1 for d in devices if d['kind'] == 'wled'),
            'obs':         sum(1 for d in devices if d['kind'] == 'obs'),
            'created':     created,
            'updated':     updated,
        }
        _progress.update(state='done', summary=summary)
        print('[discovery]', summary)
        return summary


def start_scan(app):
    """Launch scan_and_record on a daemon thread. Returns False if a scan is
    already in progress (so a double-clicked button doesn't stack sweeps)."""
    if _scan_lock.locked():
        return False

    def _run():
        try:
            scan_and_record(app)
        except Exception as e:
            _progress.update(state='error', summary=None)
            print('[discovery] scan failed:', e)

    _progress.update(state='sweeping', done=0, total=0, summary=None)
    threading.Thread(target=_run, daemon=True).start()
    return True
