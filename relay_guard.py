"""Boot crash guard for the relay connection.

A low-memory box (e.g. a Pi Zero W) can crash while the relay connects and
syncs at startup — and because relay_enabled persists in app settings, every
reboot repeats the same crash: a boot loop.

Guard: ARM a sentinel file just before relay bring-up and DISARM it once the
app has stayed alive through a grace period. Finding the sentinel still armed
at the NEXT boot means the previous bring-up took the app down — so that boot
skips the relay and flips relay_enabled off, letting the box come up healthy.
The DM re-enables the relay from the Relay page when ready.

Pure file operations, no Flask imports — app.py owns the boot decision.
"""
import os
import threading

_START_DIR = os.path.dirname(os.path.realpath(__file__))
GUARD_PATH = os.path.join(_START_DIR, '.relay_boot_guard')
GRACE_SECONDS = 90


def tripped(path=None):
    """True when a previous relay bring-up never survived its grace period."""
    return os.path.exists(path or GUARD_PATH)


def arm(path=None):
    with open(path or GUARD_PATH, 'w') as f:
        f.write('relay bring-up in progress\n')


def disarm(path=None):
    try:
        os.remove(path or GUARD_PATH)
    except OSError:
        pass


def disarm_after_grace(path=None, seconds=None):
    """Disarm on a daemon timer: if the process dies before the timer fires,
    the sentinel survives and the next boot knows the bring-up was fatal."""
    t = threading.Timer(seconds if seconds is not None else GRACE_SECONDS,
                        disarm, args=(path,))
    t.daemon = True
    t.start()
    return t
