"""Scene-end detection for the player workers.

The music and video players run as forked processes (Linux) or daemon
threads (Windows) with no Flask app context, so they cannot call the LED /
WLED fan-out directly. When one of them drains its queue it calls
notify_if_scene_ended(): if the current scene had media and EVERY queue is
now idle (sql.scene_media_finished), it asks the web process to turn the
lights off over loopback — the same session-less-endpoint pattern cron and
the browser extensions use.

Failure here must never disturb playback: every path swallows and logs.
"""
import logging

import requests

import sql

log = logging.getLogger(__name__)

APP_PORT = 8086                      # app.py hardcodes it
LIGHTS_OFF_URL = f'http://127.0.0.1:{APP_PORT}/api/lights-off'
TIMEOUT = 6                          # the push itself waits on LAN devices


def notify_if_scene_ended(post=requests.post):
    """Return True when the lights-off request was sent."""
    try:
        if not sql.scene_media_finished():
            return False
    except Exception as exc:                      # pragma: no cover - defensive
        log.warning('scene-end check failed: %s', exc)
        return False
    try:
        post(LIGHTS_OFF_URL, timeout=TIMEOUT)
        log.info('scene media finished — lights off requested')
        return True
    except Exception as exc:
        log.warning('lights-off request failed: %s', exc)
        return False
