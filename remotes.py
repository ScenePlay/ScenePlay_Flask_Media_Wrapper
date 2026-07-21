

import logging
import requests
import json
from extensions import *

from sql import *
from models.serverIP import tblserversip as IP
from models.serverRole import tblserverrole as Role
from sqlalchemy import select

log = logging.getLogger(__name__)

# A Remote-role device is another ScenePlay box, so its receive endpoint is on
# the same LAN port this app serves.
REMOTE_PORT = 8086
# Every push carries this timeout — without it, a single powered-off Remote hung
# scene activation indefinitely (requests.post blocks with no deadline).
REMOTE_TIMEOUT = 4


def _record_remote_fail(ip_address, err):
    """Persist the most recent failed LED transfer so the navbar can flag it
    DURING play — each dead Remote costs a REMOTE_TIMEOUT stall on every
    scene switch, and the console warning is invisible at the table."""
    try:
        from datetime import datetime, timezone
        ts = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
        appsettingSet('remote_send_last_fail', f'{ts}|{ip_address}|{str(err)[:120]}')
    except Exception:
        pass   # never let telemetry break the push loop


def remoteSend(LEDPattern):
    # Parse once up front; a malformed pattern should fail here, not per device.
    try:
        payload = json.loads(LEDPattern)
    except (ValueError, TypeError) as err:
        log.warning("remoteSend: bad LED pattern JSON: %s", err)
        return

    # Use the app's db session (this runs inside a request) instead of a second
    # long-lived engine/session created at import time.
    query = (select(IP, Role)
             .where(Role.ID == IP.serverroleid)
             .where(Role.name == 'Remote')
             .where(IP.active == 1))
    for row in db.session.execute(query).fetchall():
        ip_address = str(row[0].ipAddress)
        api_url = f"http://{ip_address}:{REMOTE_PORT}/receive_led_patterns"
        try:
            requests.post(api_url, json=payload, timeout=REMOTE_TIMEOUT)
            # This device answered — if IT was the one flagged, it recovered:
            # clear immediately. Success on one box never clears another
            # box's failure.
            try:
                rec = appsettingGet('remote_send_last_fail', '')
                if rec and f'|{ip_address}|' in rec:
                    appsettingSet('remote_send_last_fail', '')
            except Exception:
                pass
        except requests.RequestException as err:
            # One unreachable Remote must not stop the others.
            log.warning("remoteSend to %s failed: %s", ip_address, err)
            _record_remote_fail(ip_address, err)
        
def prepJsonRemote(ledMdl, scnPat, isLocal=False) -> str:
    """Build the ONE RPiLED payload used everywhere: local pickup via
    tblLED -> led_Run.py, other ScenePlay boxes via remoteSend, and remote
    players' home Pis via the relay.

    Every pattern carries the FULL field set (type, color, cdiff, wait_ms,
    iterations, direction — plus outPinID/brightness locally) regardless of
    pattern type; each receiver simply uses what it needs. The old builder
    included a field only if the model's TEMPLATE happened to mention it,
    which made every pattern type a different shape (and broke led_Run's
    branches that hard-index missing keys), emitted invalid JSON for
    multi-pattern scenes, and paired scene values with the wrong template
    when models arrived out of order (IN-query order != OrderBy order).

    Scene values win; the model template supplies the default for anything
    the scene row left NULL. scnPat row shape (tblScenePattern):
      [0] scenePattern_ID  [1] scene_ID  [2] ledTypeModel_ID  [3] color
      [4] wait_ms  [5] iterations  [6] direction  [7] cdiff
      [8] orderBy  [9] outPin  [10] brightness
    """
    models = {}                        # ledTypeModel_ID -> template dict
    for m in ledMdl:                   # (id, modelName, ledJSON)
        try:
            models[m[0]] = json.loads(m[2])
        except (ValueError, TypeError):
            models[m[0]] = {}

    def _num(v, dflt):
        if v is None or v == '':
            return dflt
        try:
            f = float(v)
            return int(f) if f.is_integer() else f
        except (TypeError, ValueError):
            return dflt

    def _rgb(v, dflt):
        if isinstance(v, list):
            return v
        try:
            out = json.loads(str(v))
            return out if isinstance(out, list) else dflt
        except (TypeError, ValueError):
            return dflt

    patterns = []
    for sp in scnPat:                  # authoritative: scene order (OrderBy)
        t = models.get(sp[2])
        if not t or 'type' not in t:
            continue                   # model row deleted — skip this pattern
        p = {
            'type':       t['type'],
            'color':      _rgb(sp[3], t.get('color', [0, 0, 0])),
            'cdiff':      _rgb(sp[7], t.get('cdiff', [0, 0, 0])),
            'wait_ms':    _num(sp[4], t.get('wait_ms', 30)),
            'iterations': _num(sp[5], t.get('iterations', 9999999)),
            'direction':  _num(sp[6], t.get('direction', 1)),
        }
        if isLocal:
            p['outPinID']   = _num(sp[9], 0)
            p['brightness'] = _num(sp[10], 1.0)
        patterns.append(p)

    # After a FINITE pattern finishes, fall to lights-off (preserves the old
    # builder's trailing solid; a no-op for the usual infinite patterns).
    if patterns and patterns[-1]['type'] != 'solid':
        patterns.append({'type': 'solid', 'color': [0, 0, 0],
                         'cdiff': [0, 0, 0], 'wait_ms': 30,
                         'iterations': 9999999, 'direction': 1})
    return json.dumps({'patterns': patterns})