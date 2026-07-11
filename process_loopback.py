"""Windows per-process audio capture (WASAPI process loopback).

Vendored from the AudioChannels project (audiochannels/backends/
process_loopback.py) for relay_audio_stream, with one change: read()
returns raw float32 interleaved BYTES instead of a numpy array — the only
consumer pipes them straight into ffmpeg's stdin, so numpy isn't needed.

Wraps the Windows 10 2004+ "process loopback" activation: an IAudioClient
bound to a process tree instead of a device, so we can capture one app's
audio (e.g. the music mpv) regardless of what else is playing. The
`soundcard` library has no support for this, hence the raw COM interop:
ActivateAudioInterfaceAsync on the virtual device path VAD\\Process_Loopback
with an AUDIOCLIENT_ACTIVATION_PARAMS blob naming the target PID.

Requires the `comtypes` and `pycaw` packages (Windows only). Import fails on
non-Windows platforms; callers must guard.
"""

from __future__ import annotations

import ctypes
import threading
from ctypes import POINTER, byref, sizeof, wintypes

import comtypes
from comtypes import COMMETHOD, GUID, HRESULT, IUnknown, COMObject

from pycaw.api.audioclient import IAudioClient, WAVEFORMATEX

SAMPLE_RATE = 48_000
CHANNELS = 2

_VIRTUAL_DEVICE = "VAD\\Process_Loopback"
_ACTIVATION_TYPE_PROCESS_LOOPBACK = 1
PROCESS_LOOPBACK_MODE_INCLUDE = 0
PROCESS_LOOPBACK_MODE_EXCLUDE = 1

_AUDCLNT_SHAREMODE_SHARED = 0
_AUDCLNT_STREAMFLAGS_LOOPBACK = 0x00020000
_AUDCLNT_STREAMFLAGS_EVENTCALLBACK = 0x00040000
_AUDCLNT_BUFFERFLAGS_SILENT = 0x2
_WAVE_FORMAT_IEEE_FLOAT = 3
_VT_BLOB = 65
_WAIT_OBJECT_0 = 0

_kernel32 = ctypes.windll.kernel32


class _ProcessLoopbackParams(ctypes.Structure):
    _fields_ = [("TargetProcessId", wintypes.DWORD),
                ("ProcessLoopbackMode", ctypes.c_int)]


class _ActivationParams(ctypes.Structure):
    _fields_ = [("ActivationType", ctypes.c_int),
                ("ProcessLoopbackParams", _ProcessLoopbackParams)]


class _Blob(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.ULONG),
                ("pBlobData", POINTER(ctypes.c_byte))]


class _PropVariant(ctypes.Structure):
    """Just enough PROPVARIANT to carry a VT_BLOB."""
    _fields_ = [("vt", ctypes.c_ushort),
                ("wReserved1", ctypes.c_ushort),
                ("wReserved2", ctypes.c_ushort),
                ("wReserved3", ctypes.c_ushort),
                ("blob", _Blob)]


class IActivateAudioInterfaceAsyncOperation(IUnknown):
    _iid_ = GUID("{72A22D78-CDE4-431D-B8CC-843A71199B6D}")
    _methods_ = [
        COMMETHOD([], HRESULT, "GetActivateResult",
                  (["out"], POINTER(HRESULT), "activateResult"),
                  (["out"], POINTER(POINTER(IUnknown)), "activatedInterface")),
    ]


class IActivateAudioInterfaceCompletionHandler(IUnknown):
    _iid_ = GUID("{41D949AB-9862-444A-80F6-C261334DA5EB}")
    _methods_ = [
        COMMETHOD([], HRESULT, "ActivateCompleted",
                  (["in"], POINTER(IUnknown), "activateOperation")),
    ]


class IAgileObject(IUnknown):
    """Marker interface: lets the callback fire from any COM apartment."""
    _iid_ = GUID("{94EA2B94-E9CC-49E0-C0FF-EE64CA8F5B90}")
    _methods_ = []


class IAudioCaptureClient(IUnknown):
    _iid_ = GUID("{C8ADBD64-E71E-48A0-A4DE-185C395CD317}")
    _methods_ = [
        COMMETHOD([], HRESULT, "GetBuffer",
                  (["out"], POINTER(POINTER(ctypes.c_byte)), "ppData"),
                  (["out"], POINTER(ctypes.c_uint32), "pNumFramesToRead"),
                  (["out"], POINTER(ctypes.c_uint32), "pdwFlags"),
                  (["out"], POINTER(ctypes.c_uint64), "pu64DevicePosition"),
                  (["out"], POINTER(ctypes.c_uint64), "pu64QPCPosition")),
        COMMETHOD([], HRESULT, "ReleaseBuffer",
                  (["in"], ctypes.c_uint32, "NumFramesRead")),
        COMMETHOD([], HRESULT, "GetNextPacketSize",
                  (["out"], POINTER(ctypes.c_uint32), "pNumFramesInNextPacket")),
    ]


class _CompletionHandler(COMObject):
    _com_interfaces_ = [IActivateAudioInterfaceCompletionHandler, IAgileObject]

    def __init__(self) -> None:
        super().__init__()
        self.done = threading.Event()

    def ActivateCompleted(self, *args) -> int:
        self.done.set()
        return 0


_mmdevapi = ctypes.OleDLL("Mmdevapi")
_mmdevapi.ActivateAudioInterfaceAsync.argtypes = [
    wintypes.LPCWSTR,
    POINTER(GUID),
    POINTER(_PropVariant),
    POINTER(IActivateAudioInterfaceCompletionHandler),
    POINTER(POINTER(IActivateAudioInterfaceAsyncOperation)),
]


def _activate(pid: int, mode: int) -> "ctypes.POINTER(IAudioClient)":
    params = _ActivationParams()
    params.ActivationType = _ACTIVATION_TYPE_PROCESS_LOOPBACK
    params.ProcessLoopbackParams.TargetProcessId = pid
    params.ProcessLoopbackParams.ProcessLoopbackMode = mode

    pv = _PropVariant()
    pv.vt = _VT_BLOB
    pv.blob.cbSize = sizeof(params)
    pv.blob.pBlobData = ctypes.cast(byref(params), POINTER(ctypes.c_byte))

    handler = _CompletionHandler()
    handler_ptr = handler.QueryInterface(IActivateAudioInterfaceCompletionHandler)
    operation = POINTER(IActivateAudioInterfaceAsyncOperation)()
    _mmdevapi.ActivateAudioInterfaceAsync(
        _VIRTUAL_DEVICE, byref(IAudioClient._iid_), byref(pv),
        handler_ptr, byref(operation))
    if not handler.done.wait(timeout=5):
        raise RuntimeError("process-loopback activation timed out")
    hr, punk = operation.GetActivateResult()
    if hr < 0:
        raise OSError(None, "process-loopback activation failed", None, hr & 0xFFFFFFFF)
    return punk.QueryInterface(IAudioClient)


def _capture_format() -> WAVEFORMATEX:
    wfx = WAVEFORMATEX()
    wfx.wFormatTag = _WAVE_FORMAT_IEEE_FLOAT
    wfx.nChannels = CHANNELS
    wfx.nSamplesPerSec = SAMPLE_RATE
    wfx.wBitsPerSample = 32
    wfx.nBlockAlign = CHANNELS * 4
    wfx.nAvgBytesPerSec = SAMPLE_RATE * wfx.nBlockAlign
    wfx.cbSize = 0
    return wfx


class ProcessLoopbackCapture:
    """Captures one process tree's audio as float32 stereo 48 kHz bytes.

    Usage (from a dedicated thread):
        cap = ProcessLoopbackCapture(pid)
        cap.open()
        while ...:
            block = cap.read(timeout_ms=100)   # interleaved f32le bytes or None
        cap.close()
    """

    def __init__(self, pid: int,
                 mode: int = PROCESS_LOOPBACK_MODE_INCLUDE) -> None:
        self._pid = pid
        self._mode = mode
        self._client = None
        self._capture = None
        self._event = None
        self._com_inited = False

    def open(self) -> None:
        try:
            comtypes.CoInitializeEx(comtypes.COINIT_MULTITHREADED)
        except OSError:
            pass  # already initialized on this thread (e.g. as STA)
        self._com_inited = True
        self._client = _activate(self._pid, self._mode)
        wfx = _capture_format()
        # 100 ns units: 200 ms buffer gives plenty of slack for a Python reader
        self._client.Initialize(
            _AUDCLNT_SHAREMODE_SHARED,
            _AUDCLNT_STREAMFLAGS_LOOPBACK | _AUDCLNT_STREAMFLAGS_EVENTCALLBACK,
            2_000_000, 0, ctypes.pointer(wfx), None)
        self._event = _kernel32.CreateEventW(None, False, False, None)
        self._client.SetEventHandle(self._event)
        service = self._client.GetService(byref(IAudioCaptureClient._iid_))
        self._capture = service.QueryInterface(IAudioCaptureClient)
        self._client.Start()

    def read(self, timeout_ms: int = 100):
        """Drain all pending packets; returns interleaved f32le bytes or None."""
        if _kernel32.WaitForSingleObject(self._event, timeout_ms) != _WAIT_OBJECT_0:
            return None
        chunks = []
        while self._capture.GetNextPacketSize() > 0:
            data, frames, flags, _pos, _qpc = self._capture.GetBuffer()
            if flags & _AUDCLNT_BUFFERFLAGS_SILENT:
                chunks.append(b"\x00" * (frames * CHANNELS * 4))
            else:
                chunks.append(ctypes.string_at(data, frames * CHANNELS * 4))
            self._capture.ReleaseBuffer(frames)
        if not chunks:
            return None
        return b"".join(chunks)

    def close(self) -> None:
        if self._client is not None:
            try:
                self._client.Stop()
            except OSError:
                pass
        self._capture = None
        self._client = None
        if self._event:
            _kernel32.CloseHandle(self._event)
            self._event = None
        if self._com_inited:
            comtypes.CoUninitialize()
            self._com_inited = False
