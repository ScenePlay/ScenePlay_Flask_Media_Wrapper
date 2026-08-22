

import logging
import requests
import json
from extensions import *

from sql import *
from models.serverIP import tblserversip as IP
from models.serverRole import tblserverrole as Role
from sqlalchemy import select
import relay_broadcaster
from ledPlayer import is_raspberry_pi, threaderLED

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
        

def dispatch_led(payload, local=True):
    """Send one wire payload ({"patterns": [...]} JSON string, see
    led_patterns.build_payload) everywhere a scene's lighting goes: every
    active Remote-role ScenePlay box on the LAN, the relay (remote players'
    home Pis), and — on a Pi — this box's own strip via the tblLED mailbox.
    One payload for all; each receiver applies its own hardware cap."""
    remoteSend(payload)
    relay_broadcaster.broadcast_led(payload)
    if local and is_raspberry_pi():
        insert_LEDJSON(payload)
        threaderLED()
