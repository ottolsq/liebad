"""Capture the audio of one process tree through Windows process loopback."""

from __future__ import annotations

import ctypes
import threading
import time
from ctypes import POINTER, Structure, Union, byref, c_uint32, c_uint64, c_void_p, sizeof
from ctypes import wintypes
from ctypes.wintypes import BYTE, DWORD, LPCWSTR, WORD
from typing import Callable, Iterator, Protocol, Sequence

import numpy as np
from comtypes import COMMETHOD, COMError, GUID, HRESULT, COMObject, IUnknown

from ..contracts import FRAME_SAMPLES, SAMPLE_RATE, AudioBlock

VIRTUAL_AUDIO_DEVICE_PROCESS_LOOPBACK = "VAD\\Process_Loopback"
AUDIOCLIENT_ACTIVATION_TYPE_PROCESS_LOOPBACK = 1
PROCESS_LOOPBACK_MODE_INCLUDE_TARGET_PROCESS_TREE = 0
AUDCLNT_SHAREMODE_SHARED = 0
AUDCLNT_STREAMFLAGS_LOOPBACK = 0x00020000
AUDCLNT_BUFFERFLAGS_SILENT = 0x2
VT_BLOB = 65
BUFFER_DURATION = 2_000_000  # 200 ms in 100 ns units
ACTIVATION_TIMEOUT = 5.0
SILENT_PACKET_LIMIT = 64

SYNCHRONIZE = 0x00100000
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
WAIT_OBJECT_0 = 0
WAIT_TIMEOUT = 258
RPC_E_CHANGED_MODE = -2147417850
PM_REMOVE = 0x0001


class ProcessLoopbackError(RuntimeError):
    """Capture could not start, or the target process went away."""


class _ProcessLoopbackParams(Structure):
    _fields_ = [("TargetProcessId", DWORD), ("ProcessLoopbackMode", DWORD)]


class _ActivationUnion(Union):
    _fields_ = [("ProcessLoopbackParams", _ProcessLoopbackParams)]


class AUDIOCLIENT_ACTIVATION_PARAMS(Structure):
    _fields_ = [("ActivationType", DWORD), ("u", _ActivationUnion)]


class _Blob(Structure):
    _fields_ = [("cbSize", DWORD), ("pBlobData", c_void_p)]


class PROPVARIANT(Structure):
    class _Value(Union):
        _fields_ = [("blob", _Blob)]

    _anonymous_ = ("value",)
    _fields_ = [
        ("vt", WORD),
        ("reserved1", WORD),
        ("reserved2", WORD),
        ("reserved3", WORD),
        ("value", _Value),
    ]


class WAVEFORMATEX(Structure):
    _fields_ = [
        ("wFormatTag", WORD),
        ("nChannels", WORD),
        ("nSamplesPerSec", DWORD),
        ("nAvgBytesPerSec", DWORD),
        ("nBlockAlign", WORD),
        ("wBitsPerSample", WORD),
        ("cbSize", WORD),
    ]


def _wave_format(sample_rate: int, channels: int) -> WAVEFORMATEX:
    block_align = channels * 2
    return WAVEFORMATEX(
        wFormatTag=1,
        nChannels=channels,
        nSamplesPerSec=sample_rate,
        nAvgBytesPerSec=sample_rate * block_align,
        nBlockAlign=block_align,
        wBitsPerSample=16,
        cbSize=0,
    )


class IActivateAudioInterfaceAsyncOperation(IUnknown):
    _iid_ = GUID("{72A22D78-CDE4-431D-B8CC-843A71199B6D}")
    _methods_ = [
        COMMETHOD(
            [],
            HRESULT,
            "GetActivateResult",
            (["out"], POINTER(HRESULT), "activateResult"),
            (["out"], POINTER(POINTER(IUnknown)), "activatedInterface"),
        ),
    ]


class IActivateAudioInterfaceCompletionHandler(IUnknown):
    _iid_ = GUID("{41D949AB-9862-444A-80F6-C261334DA5EB}")
    _methods_ = [
        COMMETHOD(
            [],
            HRESULT,
            "ActivateCompleted",
            (["in"], POINTER(IActivateAudioInterfaceAsyncOperation), "activateOperation"),
        ),
    ]


class IAgileObject(IUnknown):
    """Marker interface: the activation handler must be apartment agnostic."""

    _iid_ = GUID("{94EA2B94-E9CC-49E0-C0FF-EE64CA8F5B90}")
    _methods_: list = []


class IAudioClient(IUnknown):
    _iid_ = GUID("{1CB9AD4C-DBFA-4C32-B178-C2F568A703B2}")
    _methods_ = [
        COMMETHOD(
            [],
            HRESULT,
            "Initialize",
            (["in"], ctypes.c_int, "ShareMode"),
            (["in"], DWORD, "StreamFlags"),
            (["in"], ctypes.c_longlong, "hnsBufferDuration"),
            (["in"], ctypes.c_longlong, "hnsPeriodicity"),
            (["in"], POINTER(WAVEFORMATEX), "pFormat"),
            (["in"], POINTER(GUID), "AudioSessionGuid"),
        ),
        COMMETHOD([], HRESULT, "GetBufferSize", (["out"], POINTER(c_uint32), "pNumBufferFrames")),
        COMMETHOD([], HRESULT, "GetStreamLatency", (["out"], POINTER(ctypes.c_longlong), "phnsLatency")),
        COMMETHOD([], HRESULT, "GetCurrentPadding", (["out"], POINTER(c_uint32), "pNumPaddingFrames")),
        COMMETHOD(
            [],
            HRESULT,
            "IsFormatSupported",
            (["in"], ctypes.c_int, "ShareMode"),
            (["in"], POINTER(WAVEFORMATEX), "pFormat"),
            (["out"], POINTER(POINTER(WAVEFORMATEX)), "ppClosestMatch"),
        ),
        COMMETHOD([], HRESULT, "GetMixFormat", (["out"], POINTER(POINTER(WAVEFORMATEX)), "ppDeviceFormat")),
        COMMETHOD(
            [],
            HRESULT,
            "GetDevicePeriod",
            (["out"], POINTER(ctypes.c_longlong), "phnsDefaultDevicePeriod"),
            (["out"], POINTER(ctypes.c_longlong), "phnsMinimumDevicePeriod"),
        ),
        COMMETHOD([], HRESULT, "Start"),
        COMMETHOD([], HRESULT, "Stop"),
        COMMETHOD([], HRESULT, "Reset"),
        COMMETHOD([], HRESULT, "SetEventHandle", (["in"], wintypes.HANDLE, "eventHandle")),
        COMMETHOD(
            [],
            HRESULT,
            "GetService",
            (["in"], POINTER(GUID), "riid"),
            (["out"], POINTER(POINTER(IUnknown)), "ppv"),
        ),
    ]


class IAudioCaptureClient(IUnknown):
    _iid_ = GUID("{C8ADBD64-E71E-48A0-A4DE-185C395CD317}")
    _methods_ = [
        COMMETHOD(
            [],
            HRESULT,
            "GetBuffer",
            (["out"], POINTER(POINTER(BYTE)), "ppData"),
            (["out"], POINTER(c_uint32), "pNumFramesToRead"),
            (["out"], POINTER(DWORD), "pdwFlags"),
            (["out"], POINTER(c_uint64), "pu64DevicePosition"),
            (["out"], POINTER(c_uint64), "pu64QPCPosition"),
        ),
        COMMETHOD([], HRESULT, "ReleaseBuffer", (["in"], c_uint32, "NumFramesRead")),
        COMMETHOD([], HRESULT, "GetNextPacketSize", (["out"], POINTER(c_uint32), "pNumFramesInNextPacket")),
    ]


class _ActivationHandler(COMObject):
    _com_interfaces_ = [IActivateAudioInterfaceCompletionHandler, IAgileObject]

    def __init__(self) -> None:
        super().__init__()
        self.completed = threading.Event()
        self.client: POINTER(IAudioClient) | None = None
        self.error: Exception | None = None

    def ActivateCompleted(self, operation) -> int:
        try:
            result, unknown = operation.GetActivateResult()
            if result != 0:
                raise ProcessLoopbackError(
                    f"GetActivateResult failed: 0x{result & 0xFFFFFFFF:08X}"
                )
            self.client = unknown.QueryInterface(IAudioClient)
        except Exception as exc:  # pragma: no cover - COM callback
            self.error = exc
        finally:
            self.completed.set()
        return 0


def _pump_until(event: threading.Event, timeout: float) -> bool:
    """Wait for a COM callback, dispatching window messages for STA callers."""
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.PeekMessageW.restype = ctypes.c_int
    message = wintypes.MSG()
    deadline = time.monotonic() + timeout
    while not event.is_set() and time.monotonic() < deadline:
        if user32.PeekMessageW(byref(message), None, 0, 0, PM_REMOVE) <= 0:
            time.sleep(0.005)
            continue
        user32.TranslateMessage(byref(message))
        user32.DispatchMessageW(byref(message))
    return event.is_set()


def _activate_client(pid: int) -> POINTER(IAudioClient):
    params = AUDIOCLIENT_ACTIVATION_PARAMS()
    params.ActivationType = AUDIOCLIENT_ACTIVATION_TYPE_PROCESS_LOOPBACK
    params.u.ProcessLoopbackParams.TargetProcessId = pid
    params.u.ProcessLoopbackParams.ProcessLoopbackMode = (
        PROCESS_LOOPBACK_MODE_INCLUDE_TARGET_PROCESS_TREE
    )

    prop = PROPVARIANT()
    prop.vt = VT_BLOB
    prop.value.blob.cbSize = sizeof(params)
    prop.value.blob.pBlobData = ctypes.cast(byref(params), c_void_p)

    handler = _ActivationHandler()
    handler_pointer = handler.QueryInterface(IActivateAudioInterfaceCompletionHandler)

    function = ctypes.WinDLL("mmdevapi", use_last_error=True).ActivateAudioInterfaceAsync
    function.restype = ctypes.c_long
    function.argtypes = [
        LPCWSTR,
        POINTER(GUID),
        POINTER(PROPVARIANT),
        c_void_p,
        POINTER(POINTER(IActivateAudioInterfaceAsyncOperation)),
    ]
    operation = POINTER(IActivateAudioInterfaceAsyncOperation)()
    result = function(
        VIRTUAL_AUDIO_DEVICE_PROCESS_LOOPBACK,
        byref(IAudioClient._iid_),
        byref(prop),
        ctypes.cast(handler_pointer, c_void_p),
        byref(operation),
    )
    if result != 0:
        raise ProcessLoopbackError(f"ActivateAudioInterfaceAsync failed: 0x{result & 0xFFFFFFFF:08X}")
    if not _pump_until(handler.completed, ACTIVATION_TIMEOUT):
        raise ProcessLoopbackError("process loopback activation timed out")
    if handler.error is not None:
        raise handler.error
    if handler.client is None:
        raise ProcessLoopbackError("process loopback activation returned no client")
    return handler.client


def _clamp(value: float) -> float:
    if value > 1.0:
        return 1.0
    if value < -1.0:
        return -1.0
    return value


class LoopbackClient(Protocol):
    """Low level capture used by :class:`ProcessLoopbackSource`."""

    def open(self) -> None: ...

    def read_packets(self) -> list[Sequence[float]]: ...

    def close(self) -> None: ...


class ProcessProbe(Protocol):
    def alive(self) -> bool: ...

    def close(self) -> None: ...


class _ProcessProbe:
    """Reports whether the captured process still runs."""

    def __init__(self, pid: int) -> None:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._wait = kernel32.WaitForSingleObject
        self._handle = kernel32.OpenProcess(
            SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION, False, pid
        )

    def alive(self) -> bool:
        if not self._handle:
            return False
        result = self._wait(self._handle, 0)
        return result == WAIT_TIMEOUT

    def close(self) -> None:
        if self._handle:
            ctypes.WinDLL("kernel32", use_last_error=True).CloseHandle(self._handle)
            self._handle = 0


class WasapiProcessLoopbackClient:
    """WASAPI client that captures the process tree rooted at ``pid``."""

    def __init__(self, pid: int, *, sample_rate: int = SAMPLE_RATE) -> None:
        self._pid = pid
        self._sample_rate = sample_rate
        self._client = None
        self._capture = None
        self._converter = None
        self._block_align = 2
        self._com_initialized = False

    def open(self) -> None:
        import comtypes

        try:
            comtypes.CoInitializeEx(comtypes.COINIT_MULTITHREADED)
            self._com_initialized = True
        except OSError as exc:
            if getattr(exc, "winerror", None) != RPC_E_CHANGED_MODE:
                raise
        try:
            client = _activate_client(self._pid)
            self._client = client
            self._prepare_stream(client)
            capture = client.GetService(IAudioCaptureClient._iid_)
            self._capture = capture.QueryInterface(IAudioCaptureClient)
            client.Start()
        except Exception:
            self.close()
            raise

    def _prepare_stream(self, client) -> None:
        from ..audio.pcm import Pcm16kConverter

        try:
            wave_format = _wave_format(self._sample_rate, 1)
            client.Initialize(
                AUDCLNT_SHAREMODE_SHARED,
                AUDCLNT_STREAMFLAGS_LOOPBACK,
                BUFFER_DURATION,
                0,
                byref(wave_format),
                None,
            )
            self._block_align = 2
            return
        except COMError:
            pass
        mix_format = client.GetMixFormat()
        format_info = mix_format.contents
        sample_format = _sample_format(format_info.wFormatTag, format_info.wBitsPerSample)
        self._converter = Pcm16kConverter(
            format_info.nSamplesPerSec, format_info.nChannels, sample_format
        )
        self._block_align = format_info.nBlockAlign
        client.Initialize(
            AUDCLNT_SHAREMODE_SHARED,
            AUDCLNT_STREAMFLAGS_LOOPBACK,
            BUFFER_DURATION,
            0,
            mix_format,
            None,
        )

    def read_packets(self) -> list[Sequence[float]]:
        packets: list[Sequence[float]] = []
        if self._capture is None:
            return packets
        while len(packets) < SILENT_PACKET_LIMIT:
            frames = self._capture.GetNextPacketSize()
            if not frames:
                break
            data, frames, flags, _position, _qpc = self._capture.GetBuffer()
            try:
                if flags & AUDCLNT_BUFFERFLAGS_SILENT:
                    samples: Sequence[float] = [0.0] * frames
                else:
                    raw = ctypes.string_at(data, frames * self._block_align)
                    samples = self._convert(raw)
            finally:
                self._capture.ReleaseBuffer(frames)
            packets.append(samples)
        return packets

    def _convert(self, raw: bytes) -> Sequence[float]:
        if self._converter is not None:
            return self._converter.convert(raw)
        array = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        return array.tolist()

    def close(self) -> None:
        if self._client is not None:
            try:
                self._client.Stop()
            except Exception:
                pass
        self._capture = None
        self._client = None
        self._converter = None
        if self._com_initialized:
            import comtypes

            try:
                comtypes.CoUninitialize()
            except Exception:
                pass
            self._com_initialized = False


def _sample_format(format_tag: int, bits: int) -> str:
    if bits == 32:
        return "flt"
    if bits == 16:
        return "s16"
    raise ProcessLoopbackError(f"unsupported capture format: tag {format_tag}, {bits} bit")


class ProcessLoopbackSource:
    """Audio source that yields the audio of one process tree at 16 kHz mono."""

    def __init__(
        self,
        pid: int,
        *,
        gain: float = 1.0,
        client_factory: Callable[[int], LoopbackClient] | None = None,
        process_probe: ProcessProbe | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        silence_gap: float = 0.08,
        poll_interval: float = 0.004,
        probe_interval: float = 0.5,
        frame_samples: int = FRAME_SAMPLES,
    ) -> None:
        self.pid = pid
        self._gain = gain
        self._client_factory = client_factory or WasapiProcessLoopbackClient
        self._process_probe = process_probe
        self._clock = clock
        self._sleep = sleep
        self._silence_gap = silence_gap
        self._poll_interval = poll_interval
        self._probe_interval = probe_interval
        self._frame_samples = frame_samples
        self._stop = threading.Event()

    def request_stop(self) -> None:
        self._stop.set()

    def blocks(self) -> Iterator[AudioBlock]:
        client = self._client_factory(self.pid)
        probe = self._process_probe or _ProcessProbe(self.pid)
        offset = 0
        try:
            client.open()
            last_audio = self._clock()
            next_silence = last_audio + self._silence_gap
            next_probe = last_audio + self._probe_interval
            while not self._stop.is_set():
                now = self._clock()
                if now >= next_probe:
                    if not probe.alive():
                        raise ProcessLoopbackError(f"target process {self.pid} exited")
                    next_probe = now + self._probe_interval
                packets = client.read_packets()
                if packets:
                    for samples in packets:
                        values = tuple(_clamp(sample * self._gain) for sample in samples)
                        yield AudioBlock(values, offset)
                        offset += len(values)
                    last_audio = now
                    next_silence = last_audio + self._silence_gap
                    continue
                if not probe.alive():
                    raise ProcessLoopbackError(f"target process {self.pid} exited")
                now = self._clock()
                if now >= next_silence:
                    yield AudioBlock((0.0,) * self._frame_samples, offset)
                    offset += self._frame_samples
                    next_silence += self._frame_samples / SAMPLE_RATE
                    if next_silence < now - 1.0:
                        next_silence = now
                else:
                    self._sleep(min(self._poll_interval, max(0.0, next_silence - now)))
        finally:
            client.close()
            probe.close()
