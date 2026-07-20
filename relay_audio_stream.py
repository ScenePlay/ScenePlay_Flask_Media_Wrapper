"""Live capture of the music player's audio, pushed to the relay portal.

Portal players hear the GM's music in their browsers: mpv's output is
captured live (so pause/seek/next and volume are all in the stream), ffmpeg
encodes it to 128 kbps MP3, and a worker thread pushes the bytes to the relay
as long chunked POSTs (rotated every few minutes to keep individual request
durations bounded through hosting proxies).

Capture mechanism (borrowed from the AudioChannels project):
- Linux: a dedicated PulseAudio/PipeWire null sink (`sceneplay_music`) that
  mpv is pointed at (see play_mp3_local / mpvAudio.sh), a loopback module so
  the GM keeps hearing it on the real speakers, and ffmpeg recording the
  sink's monitor. One continuous capture across tracks.
- Windows: per-process WASAPI loopback of the music mpv's PID (vendored
  process_loopback module), PCM piped through ffmpeg for encoding. Capture
  re-attaches on each track (mpv is one process per track).

This module runs inside the audio player's process (a separate OS process on
Linux), called from player.threader. Every public entry point swallows its
own failures — streaming must never be able to break local playback.
"""
import logging
import os
import subprocess
import threading
import time
from collections import deque

log = logging.getLogger(__name__)

_IS_WIN = os.name == "nt"

SINK_NAME = "sceneplay_music"

_CHUNK = 1024          # ~64 ms of audio at 128 kbps — small packets, smooth cadence
_POST_BATCH = 4096     # assemble small reads into ~4 KB POST writes: the relay's
                       # tiny CPU share (Render free tier) fans out 4x fewer chunks
_BACKLOG_MAX = 384 * 1024   # ~24 s at 128 kbps the backlog can bridge (see _StreamBuffer)
# End + reopen the ingest POST this often. Every rotation is a brief hole in
# the stream, so fewer is better; 15 min stays comfortably inside proxy
# request-duration limits on the paid relay tier. The kept-alive Session in
# _run() makes the reopen itself a ~1-RTT blip instead of a fresh TCP+TLS
# handshake (rotations at 300s with cold connections were an audible drop
# every 5 minutes for low-lag listeners).
_ROTATE_S = 900
_IDLE_STOP_S = 20      # capture/push stops this long after the last track
_ATTACH_WAIT_S = 10    # Windows: max wait for the new mpv PID to appear

_SUPERVISE_S = 2       # how quickly the admin streaming switch takes effect

_lock = threading.RLock()
_worker = None
_stop = threading.Event()
_supervisor = None
_playing = False
_last_end = 0.0
_current_song_id = 0   # song announced when the switch is flipped on mid-track
_track_epoch = 0       # bumped per track; Windows capture re-attaches on change
_graph_modules = []    # pactl module ids we loaded (pactl backend)
_loopback_proc = None  # pw-loopback child (pipewire backend)
_graph_ready = False
_graph_failed = False  # only log the environment problem once


# ── config ────────────────────────────────────────────────────────────────────

def _cfg_active():
    """Relay + audio-streaming config, or None when streaming shouldn't run.
    Re-read at every track start so toggles apply without a restart."""
    try:
        from sql import appsettingGet
        cfg = {
            "enabled":    appsettingGet("relay_enabled", "0"),
            "url":        appsettingGet("relay_url", ""),
            "secret":     appsettingGet("relay_secret", ""),
            "session_id": appsettingGet("relay_session_id", ""),
            "audio":      appsettingGet("relay_audio_enabled", "1"),
        }
    except Exception:
        return None
    if cfg["enabled"] != "1" or cfg["audio"] != "1" \
            or not cfg["url"] or not cfg["session_id"]:
        return None
    return cfg


def _relay_on():
    """Relay itself is enabled (regardless of the audio switch). The capture
    graph is kept up whenever this holds, so mpv is always playing into the
    sink and flipping the audio switch mid-track streams sound immediately
    instead of dead air until the next song."""
    try:
        from sql import appsettingGet
        return appsettingGet("relay_enabled", "0") == "1"
    except Exception:
        return False


# ── Linux capture graph (null sink + loopback to the GM's speakers) ──────────
# Two interchangeable backends: `pactl` where PulseAudio tooling exists, else
# native PipeWire tools (pw-cli/pw-loopback — pipewire-pulse still exposes the
# sink to mpv and ffmpeg through the pulse compatibility layer either way).

_LOOPBACK_TAG = "sceneplay-monitor"


def _run_cmd(*args):
    return subprocess.run(args, capture_output=True, text=True, timeout=5)


def _sweep_stale_pactl():
    """Unload sink/loopback modules left by a previous crash — a stale sink
    would otherwise shadow the fresh one and capture dead air."""
    out = _run_cmd("pactl", "list", "modules", "short")
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip() or "pactl unavailable")
    for line in out.stdout.splitlines():
        if SINK_NAME in line:
            _run_cmd("pactl", "unload-module", line.split()[0])


def _ensure_graph_pactl():
    global _graph_modules
    _sweep_stale_pactl()
    sink = _run_cmd("pactl", "load-module", "module-null-sink",
                    f"sink_name={SINK_NAME}",
                    "sink_properties=device.description=ScenePlay-Stream")
    if sink.returncode != 0:
        raise RuntimeError(sink.stderr.strip())
    _graph_modules.append(sink.stdout.strip())
    # GM keeps hearing the music: mirror the capture sink to the default
    # output. (Not re-pointed if the default sink changes mid-session.)
    loop = _run_cmd("pactl", "load-module", "module-loopback",
                    f"source={SINK_NAME}.monitor", "sink=@DEFAULT_SINK@",
                    f"sink_input_properties=media.name={_LOOPBACK_TAG}")
    if loop.returncode != 0:
        raise RuntimeError(loop.stderr.strip())
    _graph_modules.append(loop.stdout.strip())


def _ensure_graph_pipewire():
    global _loopback_proc
    # Sweep: the lingering sink survives crashes; orphaned pw-loopback
    # helpers are found by their distinctive --name tag.
    _run_cmd("pw-cli", "destroy", SINK_NAME)
    subprocess.run(["pkill", "-f", _LOOPBACK_TAG],
                   capture_output=True, timeout=5)
    sink = _run_cmd(
        "pw-cli", "create-node", "adapter",
        "{ factory.name=support.null-audio-sink"
        f" node.name={SINK_NAME}"
        " media.class=Audio/Sink object.linger=true"
        " audio.position=[FL FR] }")
    if sink.returncode != 0:
        raise RuntimeError(sink.stderr.strip() or "pw-cli create-node failed")
    # GM keeps hearing the music: a loopback child mirrors the sink to the
    # default output. It dies with this process; the start-time pkill above
    # reaps any orphan from a crash.
    _loopback_proc = subprocess.Popen(
        ["pw-loopback", f"--name={_LOOPBACK_TAG}",
         "--capture-props="
         f"{{target.object={SINK_NAME} stream.capture.sink=true}}"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _ensure_graph():
    """Create the capture graph once per process. Returns True when mpv can
    be pointed at SINK_NAME and ffmpeg can record its monitor."""
    global _graph_ready, _graph_failed
    if _IS_WIN:
        return True   # Windows captures the mpv process directly, no graph
    if _graph_ready:
        return True
    if _graph_failed:
        return False
    import shutil
    try:
        if shutil.which("pactl"):
            _ensure_graph_pactl()
        elif shutil.which("pw-cli") and shutil.which("pw-loopback"):
            _ensure_graph_pipewire()
        else:
            raise RuntimeError("neither pactl nor pw-cli/pw-loopback found")
        _graph_ready = True
        return True
    except Exception as e:
        _graph_failed = True
        log.warning("relay audio streaming disabled — capture sink setup "
                    "failed (%s); local playback unaffected", e)
        _teardown_graph()
        return False


def _teardown_graph():
    global _graph_ready, _graph_modules, _loopback_proc
    for mid in _graph_modules:
        try:
            _run_cmd("pactl", "unload-module", mid)
        except Exception:
            pass
    _graph_modules = []
    if _loopback_proc is not None:
        _kill(_loopback_proc)
        _loopback_proc = None
        try:
            _run_cmd("pw-cli", "destroy", SINK_NAME)
        except Exception:
            pass
    _graph_ready = False


def sink_name():
    """Sink mpv should play into, or None to use the default output.
    Called by play_mp3_local AFTER on_track_start has ensured the graph."""
    return SINK_NAME if (not _IS_WIN and _graph_ready) else None


# ── capture processes ─────────────────────────────────────────────────────────

def _bitrate():
    """Stream bitrate in kbps — the relay_audio_bitrate app setting. 128 is
    full quality; 96/64 cut listeners' (mobile) data use. Read at capture
    spawn, so it applies from the next track / rotation like the other
    audio toggles."""
    try:
        from sql import appsettingGet
        b = str(appsettingGet("relay_audio_bitrate", "128") or "128").strip()
    except Exception:
        b = "128"
    return b if b in ("64", "96", "128") else "128"


def _gain():
    """Stream loudness percent (relay_audio_gain, default 50). The capture
    sink receives mpv's output at source level, so the relayed stream was
    much hotter than what the GM hears locally — this scales the encoder
    input (ffmpeg volume filter), independent of any local volume. Read at
    capture spawn like _bitrate()."""
    try:
        from sql import appsettingGet
        g = int(str(appsettingGet("relay_audio_gain", "50") or "50").strip())
    except Exception:
        g = 50
    return g if 10 <= g <= 200 else 50


def _profile():
    """Latency profile forwarded to the relay (X-Audio-Profile header).
    'low' keeps portal listeners ~4-5 s behind live; 'smooth' trades ~10-12 s
    of delay for more armor against wifi blips (the original behavior). Read
    at stream start, so it applies from the next capture like _bitrate()."""
    try:
        from sql import appsettingGet
        p = str(appsettingGet("relay_audio_profile", "low") or "low").strip()
    except Exception:
        p = "low"
    return p if p in ("low", "smooth") else "low"


# Live-stream encoder flags: flush every packet (don't buffer frames),
# no Xing/VBR header (wrong for live; confuses some decoders on join),
# no bit reservoir (each frame self-contained -> cleaner resync when a
# slow listener drops a chunk).
_STREAM_FLAGS = ["-reservoir", "0", "-write_xing", "0", "-flush_packets", "1"]


def _gain_args():
    g = _gain()
    return [] if g == 100 else ["-af", f"volume={g / 100:.2f}"]


def _spawn_ffmpeg_linux():
    return subprocess.Popen(
        ["ffmpeg", "-hide_banner", "-loglevel", "error",
         "-f", "pulse", "-i", f"{SINK_NAME}.monitor",
         "-c:a", "libmp3lame", "-b:a", _bitrate() + "k", "-ar", "44100", "-ac", "2",
         *_gain_args(), *_STREAM_FLAGS,
         "-f", "mp3", "pipe:1"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)


def _spawn_ffmpeg_windows():
    """Encoder fed float32 PCM on stdin by the WASAPI feeder thread."""
    return subprocess.Popen(
        ["ffmpeg", "-hide_banner", "-loglevel", "error",
         "-f", "f32le", "-ar", "48000", "-ac", "2", "-i", "pipe:0",
         "-c:a", "libmp3lame", "-b:a", _bitrate() + "k", "-ar", "44100", "-ac", "2",
         *_gain_args(), *_STREAM_FLAGS,
         "-f", "mp3", "pipe:1"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def _kill(proc):
    if proc is None:
        return
    try:
        proc.kill()
        proc.wait(timeout=2)
    except Exception:
        pass


def _win_wait_for_mpv_pid(deadline):
    """The music mpv's PID appears in appsettings shortly after spawn
    (play_mp3_local stores it); wait for a live one."""
    from procutil import pid_alive
    from sql import appsettingAudioPlayPID
    while time.monotonic() < deadline and not _stop.is_set():
        try:
            pid = int(appsettingAudioPlayPID()[0][2])
            if pid > 0 and pid_alive(pid):
                return pid
        except Exception:
            pass
        time.sleep(0.25)
    return None


def _win_feeder(ffmpeg, stop_evt):
    """Windows: pump per-process WASAPI loopback PCM into ffmpeg's stdin,
    re-attaching to the new mpv whenever the track changes."""
    try:
        from process_loopback import ProcessLoopbackCapture
    except Exception as e:
        log.warning("relay audio streaming disabled — WASAPI capture "
                    "unavailable (%s)", e)
        _kill(ffmpeg)
        return
    capture = None
    epoch = -1
    try:
        while not stop_evt.is_set() and ffmpeg.poll() is None:
            if epoch != _track_epoch:
                epoch = _track_epoch
                if capture:
                    capture.close()
                    capture = None
                pid = _win_wait_for_mpv_pid(time.monotonic() + _ATTACH_WAIT_S)
                if pid:
                    capture = ProcessLoopbackCapture(pid)
                    capture.open()
            if capture is None:
                if _idle_expired():
                    break
                time.sleep(0.25)
                continue
            block = capture.read(timeout_ms=250)   # interleaved f32le bytes
            if block is None:
                continue
            ffmpeg.stdin.write(block)
            ffmpeg.stdin.flush()
    except Exception as e:
        log.warning("windows capture feeder stopped: %s", e)
    finally:
        if capture:
            try:
                capture.close()
            except Exception:
                pass
        try:
            ffmpeg.stdin.close()
        except Exception:
            pass


# ── push worker ───────────────────────────────────────────────────────────────

def _idle_expired():
    return not _playing and (time.monotonic() - _last_end) > _IDLE_STOP_S


class _StreamBuffer:
    """Bounded FIFO decoupling capture from the network.

    A reader thread drains ffmpeg into this buffer continuously, so the
    encoder can never block on a slow/broken network path — which also means
    capture KEEPS ROLLING through a relay outage. Listeners sit ~12 s behind
    live (the relay preroll), so when the push reconnects and the backlog
    drains fast, a short blip is bridged with zero audible gap instead of
    losing that stretch of audio. Overflow (outage longer than ~24 s) drops
    the oldest audio; listeners hear one jump instead of permanent lag."""

    def __init__(self, max_bytes=_BACKLOG_MAX):
        self._dq = deque()
        self._bytes = 0
        self._max = max_bytes
        self._cond = threading.Condition()
        self._closed = False

    def push(self, chunk):
        with self._cond:
            self._dq.append(chunk)
            self._bytes += len(chunk)
            while self._bytes > self._max and len(self._dq) > 1:
                self._bytes -= len(self._dq.popleft())
            self._cond.notify_all()

    def pop(self, timeout):
        """Next chunk, or None on timeout / closed-and-drained."""
        with self._cond:
            if not self._dq and not self._closed:
                self._cond.wait(timeout)
            if self._dq:
                chunk = self._dq.popleft()
                self._bytes -= len(chunk)
                return chunk
            return None

    def close(self):
        with self._cond:
            self._closed = True
            self._cond.notify_all()

    def size(self):
        with self._cond:
            return self._bytes

    def done(self):
        with self._cond:
            return self._closed and not self._dq


def _reader(proc, buf):
    """Drain ffmpeg stdout into the buffer until the encoder exits."""
    try:
        while True:
            chunk = proc.stdout.read(_CHUNK)
            if not chunk:
                break
            buf.push(chunk)
    except Exception:
        pass
    finally:
        buf.close()


def _chunks(buf, deadline):
    """Yield ~_POST_BATCH-byte writes assembled from the small capture reads:
    locally we read every ~64 ms for smooth cadence, but the relay receives
    ~4 KB every ~250 ms. Flushes whatever is pending at least every ~250 ms,
    and drains until rotation, encoder death, stop, or idle."""
    pending, pending_bytes = [], 0
    last_flush = time.monotonic()
    while not _stop.is_set() and not _idle_expired() \
            and time.monotonic() < deadline:
        chunk = buf.pop(timeout=0.25)
        if chunk is not None:
            pending.append(chunk)
            pending_bytes += len(chunk)
        now = time.monotonic()
        if pending and (pending_bytes >= _POST_BATCH or now - last_flush >= 0.25):
            yield b"".join(pending)
            pending, pending_bytes = [], 0
            last_flush = now
        if chunk is None and buf.done():
            break
    if pending:
        yield b"".join(pending)


def _spawn_capture():
    if _IS_WIN:
        ffmpeg = _spawn_ffmpeg_windows()
        threading.Thread(target=_win_feeder, args=(ffmpeg, _stop),
                         daemon=True, name="relay-audio-feeder").start()
        return ffmpeg
    return _spawn_ffmpeg_linux()


def _ws_drain(ws):
    """Reader thread: consume (and discard) inbound frames so the client
    library answers the server's keepalive pings — a send-only socket would
    never process them and the server would drop us on ping timeout.

    recv() inherits the socket's 10 s timeout, and the server normally sends
    NOTHING but a ping every ~20 s — so idle timeouts here are routine and
    must keep the loop alive. Treating them as fatal silently killed this
    thread, pong replies stopped, and the server cut the ingest off dead on
    its ping-timeout clock (the every-50-seconds stream drop)."""
    import websocket as _wslib
    while True:
        try:
            ws.recv()
        except _wslib.WebSocketTimeoutException:
            continue
        except Exception:
            break


def _push_ws(cfg, buf, first):
    """Push the stream over ONE persistent WebSocket until stop/idle/error —
    the preferred transport: no POST rotation, so no periodic stream gap.
    Returns (outcome, connected, seconds): outcome 'unsupported' = relay has
    no WS route (fall back to POST for this capture), 'done' = clean stop,
    'error' = retryable blip (backlog bridges it, reconnect with backoff)."""
    try:
        import websocket
    except ImportError:
        return "unsupported", False, 0.0
    ws_url = (cfg["url"].rstrip("/")
              .replace("https://", "wss://", 1).replace("http://", "ws://", 1)
              + f"/api/v1/session/{cfg['session_id']}/audio-ingest-ws"
              + ("" if first else "?continuation=1"))
    started = time.monotonic()
    try:
        ws = websocket.create_connection(
            ws_url, timeout=10,
            header={"X-Relay-Secret": cfg["secret"],
                    "X-Audio-Profile": _profile()})
    except websocket.WebSocketBadStatusException as e:
        # 403/404/405 = relay predates the WS route. (A bad secret surfaces
        # the same way; the POST fallback then reports it properly as a 4xx.)
        if getattr(e, "status_code", 0) in (403, 404, 405):
            return "unsupported", False, 0.0
        return "error", False, time.monotonic() - started
    except Exception:
        return "error", False, time.monotonic() - started
    threading.Thread(target=_ws_drain, args=(ws,), daemon=True,
                     name="relay-audio-ws-drain").start()
    try:
        ws.settimeout(10)
        for batch in _chunks(buf, deadline=float("inf")):
            ws.send_binary(batch)
        return "done", True, time.monotonic() - started
    except Exception:
        return "error", True, time.monotonic() - started
    finally:
        try:
            ws.close()
        except Exception:
            pass


def _run(cfg):
    """Worker thread: capture → encode → push until playback goes idle."""
    import requests
    url = (cfg["url"].rstrip("/")
           + f"/api/v1/session/{cfg['session_id']}/audio-ingest")
    headers = {"X-Relay-Secret": cfg["secret"], "Content-Type": "audio/mpeg",
               "X-Audio-Profile": _profile()}
    # One Session for the worker's lifetime: rotations reuse the pooled
    # TCP+TLS connection, shrinking the between-POST stream gap to ~1 RTT.
    http = requests.Session()
    proc = None
    buf = None
    first = True     # first push of the period clears the relay preroll
    backoff = 2
    use_ws = True    # WebSocket first; permanent POST fallback per capture
    try:
        while not _stop.is_set() and not _idle_expired():
            # Rotation boundary: honor relay/audio toggles flipped mid-playback
            if _cfg_active() is None:
                break
            if proc is None or proc.poll() is not None:
                _kill(proc)
                proc = _spawn_capture()
                buf = _StreamBuffer()
                threading.Thread(target=_reader, args=(proc, buf),
                                 daemon=True, name="relay-audio-reader").start()

            if use_ws:
                outcome, connected, dur = _push_ws(cfg, buf, first)
                if outcome == "unsupported":
                    use_ws = False
                    log.info("relay has no WebSocket ingest — using chunked POST")
                    continue
                if connected:
                    first = False
                if outcome == "done":
                    break
                if dur > 30:      # a long healthy run earns a fast reconnect
                    backoff = 2
                log.info("audio ws push interrupted after %.0fs; retrying in "
                         "%ss (backlog bridging the gap)", dur, backoff)
                if _stop.wait(backoff):
                    break
                backoff = min(10, backoff * 2)
                continue

            deadline = time.monotonic() + _ROTATE_S
            try:
                resp = http.post(
                    url + ("" if first else "?continuation=1"),
                    data=_chunks(buf, deadline),
                    headers=headers, timeout=(5, 30))
                if 400 <= resp.status_code < 500:
                    log.warning("relay refused audio ingest (%s) — streaming "
                                "off until next playback", resp.status_code)
                    break
                # Rotation boundary telemetry: a healthy stream shows ~0 KB
                # backlog here; growth means the network can't keep up.
                log.info("audio ingest rotated; backlog %.1f KB", buf.size() / 1024)
                first = False
                backoff = 2
            except Exception as e:
                # Relay unreachable mid-track: capture KEEPS running — the
                # dedicated reader thread means the encoder pipe can't block,
                # and the backlog holds the audio. On reconnect it drains
                # fast, so blips shorter than the listeners' cushion are
                # bridged seamlessly instead of leaving a hole.
                log.info("audio push interrupted (%s); retrying in %ss "
                         "(backlog bridging the gap)",
                         e.__class__.__name__, backoff)
                if _stop.wait(backoff):
                    break
                backoff = min(10, backoff * 2)
                first = False   # keep listeners attached across the blip
    finally:
        _kill(proc)
        http.close()
        # Definitive "music stopped" for the portal widget (idempotent —
        # the queue-drain path may already have sent it).
        _broadcast_now_playing(None, False)


def _ensure_worker(cfg):
    global _worker
    if _worker is not None and _worker.is_alive():
        return
    _stop.clear()
    _worker = threading.Thread(target=_run, args=(cfg,), daemon=True,
                               name="relay-audio")
    _worker.start()


def _stop_worker():
    _stop.set()


def _supervise():
    """Applies the admin 'Stream music to portal' switch within ~2 s in both
    directions, mid-track. The admin UI lives in the Flask process; this
    (player) process only shares the sqlite DB, so the switch has to be
    polled — the per-track/per-rotation checks alone made it look broken on
    long ambience tracks."""
    while True:
        time.sleep(_SUPERVISE_S)
        try:
            cfg = _cfg_active()
            with _lock:
                worker_alive = _worker is not None and _worker.is_alive()
                if cfg and _playing and not worker_alive:
                    if _ensure_graph():
                        _ensure_worker(cfg)
                        _broadcast_now_playing(_current_song_id or None, True)
                elif not cfg and worker_alive:
                    _stop.set()   # worker exits within a chunk (~250 ms)
        except Exception:
            log.debug("audio supervisor tick failed", exc_info=True)


def _ensure_supervisor():
    global _supervisor
    if _supervisor is not None and _supervisor.is_alive():
        return
    _supervisor = threading.Thread(target=_supervise, daemon=True,
                                   name="relay-audio-supervisor")
    _supervisor.start()


def _broadcast_now_playing(song_id, stream_active):
    try:
        import relay_broadcaster
        relay_broadcaster.broadcast_now_playing(song_id, stream_active)
    except Exception:
        log.debug("now-playing broadcast failed", exc_info=True)


# ── public API (called from player.threader; must never raise) ───────────────

def on_track_start(song_id):
    """Called just before mpv spawns. Ensures the capture graph exists (so
    play_mp3_local can point mpv at it), (re)starts the push worker, and
    announces the track to the portal. The graph goes up whenever the RELAY
    is enabled — even with the audio switch off — so mpv always plays into
    the sink and the switch can start streaming mid-track (the supervisor
    applies switch flips within ~2 s)."""
    global _playing, _track_epoch, _current_song_id
    try:
        with _lock:
            _playing = True
            _track_epoch += 1
            _current_song_id = song_id
            if _relay_on():
                _ensure_graph()
                _ensure_supervisor()
            cfg = _cfg_active()
            streaming = bool(cfg) and (_IS_WIN or _graph_ready)
            if streaming:
                _ensure_worker(cfg)
        _broadcast_now_playing(song_id, streaming)
    except Exception:
        log.exception("on_track_start failed (playback unaffected)")


def on_track_end():
    """Called when mpv exits (track end, next, or stop). The worker keeps
    the stream open for _IDLE_STOP_S so the next track plays gap-free; if
    nothing follows, it exits and reports playback stopped."""
    global _playing, _last_end
    try:
        _playing = False
        _last_end = time.monotonic()
    except Exception:
        pass


def on_playback_stopped():
    """Called on queue drain — a definite stop, so tell the portal now
    instead of waiting out the idle window."""
    global _current_song_id
    _current_song_id = 0
    on_track_end()
    _broadcast_now_playing(None, False)


def shutdown():
    try:
        _stop_worker()
        _teardown_graph()
    except Exception:
        pass
