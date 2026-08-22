"""Local RPiLED playback: (re)launch led_Run.py for the payload waiting in
the tblLED mailbox. Pi-only — every other platform returns False and the
caller carries on (Remote boxes and the relay are pushed separately)."""
import os
import platform
import subprocess
import time
from pathlib import Path


def is_raspberry_pi() -> bool:
    """True on a Pi that can drive a NeoPixel strip. The Pi 5 changed its
    PWM/DMA hardware and the rpi_ws281x path does not work there."""
    cpuinfo = Path('/proc/cpuinfo')
    if not cpuinfo.exists():
        return False
    try:
        if 'Raspberry Pi 5' in cpuinfo.read_text():
            return False
    except OSError:
        return False
    return platform.machine() in ('armv7l', 'armv6l', 'aarch64')


def threaderLED():
    """Kill any running led_Run.py and start a fresh one on the mailbox
    payload. Returns True if a launch happened."""
    if not is_raspberry_pi():
        return False
    s = subprocess.Popen(['sudo', 'pkill', '-9', '-f', 'led_Run.py'])
    while s.poll() is None:
        time.sleep(1 / 100)
    script = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'led_Run.py')
    subprocess.Popen(['sudo', 'python3', script])
    return True
