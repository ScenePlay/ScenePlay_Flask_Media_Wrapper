from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager
from flask_bcrypt import Bcrypt
import os

# Master-volume backend is OS-specific: PulseAudio on Linux, Windows Core
# Audio (pycaw) on Windows. Same pattern as player.py — Linux-only libraries
# are excluded behind the os.name check so the app can import on Windows.
if os.name != 'nt':
    import pulsectl

db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()
bcrypt = Bcrypt()
database = 'ScenePlay.db'
databaseDir = os.path.dirname(os.path.realpath(__file__)) + '/' + database


# --- Windows master volume: single-threaded COM worker -----------------------
# COM objects (pycaw/comtypes) are NOT safe to create in one thread and release
# in another: with waitress serving from 8 threads, the endpoint objects made
# per-request got garbage-collected on other threads, and the cross-thread
# Release is an access violation in _ctypes.pyd that kills the whole process
# (Event Viewer: python.exe faulting in _ctypes.pyd, 0xC0000005). So ONE daemon
# thread owns COM for its whole life; request threads only pass messages to it
# and never touch a COM object.
if os.name == 'nt':
    import threading
    import queue as _queue

    _audio_requests = _queue.Queue()
    _audio_thread = None
    _audio_thread_lock = threading.Lock()

    def _audio_worker():
        import comtypes
        from ctypes import POINTER, cast
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
        comtypes.CoInitialize()
        while True:
            op, val, reply = _audio_requests.get()
            result = None
            try:
                # Re-resolve the default device per request (still on THIS
                # thread only) so switching speakers/headphones is picked up.
                devices = AudioUtilities.GetSpeakers()
                interface = devices.Activate(IAudioEndpointVolume._iid_, comtypes.CLSCTX_ALL, None)
                endpoint = cast(interface, POINTER(IAudioEndpointVolume))
                if op == 'get':
                    result = round(endpoint.GetMasterVolumeLevelScalar() * 100)
                else:
                    endpoint.SetMasterVolumeLevelScalar(max(0, min(100, int(val))) / 100, None)
                del endpoint, interface, devices   # release on the COM thread, not via GC elsewhere
            except Exception:
                result = None
            if reply is not None:
                reply.put(result)

    def _audio_request(op, val=None, timeout=3.0):
        """Send one get/set to the COM thread; None on failure/timeout."""
        global _audio_thread
        with _audio_thread_lock:
            if _audio_thread is None or not _audio_thread.is_alive():
                _audio_thread = threading.Thread(target=_audio_worker, daemon=True,
                                                 name='audio-com-worker')
                _audio_thread.start()
        reply = _queue.Queue(1)
        _audio_requests.put((op, val, reply))
        try:
            return reply.get(timeout=timeout)
        except _queue.Empty:
            return None


def getmixer():
    if os.name == 'nt':
        return []   # sinks are a PulseAudio concept; setvolume handles nt directly

    with pulsectl.Pulse('volume-control') as pulse:
    # Get a list of all output devices (sinks)
        mixers = pulse.sink_list()
    return mixers

def currentvolume():
    if os.name == 'nt':
        vol = _audio_request('get')
        return vol if vol is not None else 0   # degrade to 0 rather than breaking the page

    with pulsectl.Pulse('volume-getter') as pulse:
    # 1. Get the name of the device currently acting as "Default"
        server_info = pulse.server_info()
        default_sink_name = server_info.default_sink_name

    # 2. Find that specific device (sink)
        sink = pulse.get_sink_by_name(default_sink_name)

    # 3. Calculate the volume percentage
    # value_flat gives the volume as a float (0.0 to 1.0)
    volume = round(sink.volume.value_flat * 100)

    #print(f"Device: {sink.description}")
    #print(f"Current Volume: {volume}%")
    return volume

def setvolume(volume):
    # print(volume)
    if os.name == 'nt':
        _audio_request('set', volume)
        return

    with pulsectl.Pulse('volume-control') as pulse:
        mixers = getmixer()
        for sink in mixers:
            pulse.volume_set_all_chans(sink,volume/100)
    return