"""Microphone capture converted to mono 16 kHz float blocks."""

from __future__ import annotations

import queue
import threading
from collections.abc import Callable, Iterator
from typing import Any

import sounddevice as sd

from ..contracts import SAMPLE_RATE, AudioBlock
from .pcm import Pcm16kConverter

#: Host API name used on Windows; the default driver reports WASAPI devices.
WASAPI_NAME = "Windows WASAPI"

#: Samples per callback at the device rate; ~21 ms of 48 kHz audio.
DEFAULT_BLOCKSIZE = 1024

#: Upper bound of queued raw blocks before the callback reports an overflow.
#: A 12 s segment costs several seconds of recognition on the closing path, so
#: the buffer has to absorb roughly five seconds of audio.
DEFAULT_MAX_QUEUE = 512

#: The WASAPI capture path reports speech around RMS 0.005-0.008; whisper was
#: validated with peaks near 0.3, so a modest fixed gain lifts speech into range.
DEFAULT_GAIN = 6.0


def _clamp(value: float) -> float:
    if value > 1.0:
        return 1.0
    if value < -1.0:
        return -1.0
    return value


def _wasapi_index() -> int | None:
    for index, hostapi in enumerate(sd.query_hostapis()):
        if hostapi["name"] == WASAPI_NAME:
            return index
    return None


def list_microphones() -> list[tuple[int, str]]:
    """Return ``(device id, name)`` for every WASAPI input device."""

    hostapi = _wasapi_index()
    devices: list[tuple[int, str]] = []
    for index, info in enumerate(sd.query_devices()):
        if info["max_input_channels"] <= 0:
            continue
        if hostapi is not None and info["hostapi"] != hostapi:
            continue
        devices.append((index, info["name"]))
    return devices


class MicrophoneSource:
    """Capture one WASAPI input device and hand out 16 kHz mono blocks.

    The PortAudio callback only copies bytes into a bounded queue; conversion
    and resampling run on the consumer thread. ``request_stop`` makes the
    stream drain what is already queued, flush the resampler and end.
    """

    def __init__(
        self,
        device_id: int,
        *,
        sample_rate: int | None = None,
        channels: int = 1,
        blocksize: int = DEFAULT_BLOCKSIZE,
        max_queue: int = DEFAULT_MAX_QUEUE,
        gain: float = DEFAULT_GAIN,
        stream_factory: Callable[[], Any] | None = None,
        converter_factory: Callable[[int, int], Pcm16kConverter] = Pcm16kConverter,
    ) -> None:
        self._device_id = device_id
        self._sample_rate = sample_rate
        self._channels = channels
        self._blocksize = blocksize
        self._max_queue = max_queue
        self._gain = float(gain)
        self._stream_factory = stream_factory or self._open_stream
        self._converter_factory = converter_factory
        self._queue: queue.Queue[bytes | None] = queue.Queue(maxsize=max_queue)
        self._stop = threading.Event()
        self._error: BaseException | None = None
        self._stream: Any | None = None

    @property
    def device_id(self) -> int:
        return self._device_id

    @property
    def error(self) -> BaseException | None:
        return self._error

    def _device_rate_and_channels(self) -> tuple[int, int]:
        if self._sample_rate is not None:
            return self._sample_rate, self._channels
        info = sd.query_devices(self._device_id)
        rate = int(info["default_samplerate"]) or 48_000
        channels = 2 if info["max_input_channels"] >= 2 else 1
        self._sample_rate, self._channels = rate, channels
        return rate, channels

    def _open_stream(self) -> Any:
        rate, channels = self._device_rate_and_channels()
        return sd.RawInputStream(
            device=self._device_id,
            samplerate=rate,
            channels=channels,
            dtype="int16",
            blocksize=self._blocksize,
            callback=self._callback,
        )

    def _callback(
        self,
        indata: Any,
        frames: int,
        time_info: Any,
        status: Any,
    ) -> None:
        if status:
            self._fail(RuntimeError(f"microphone status: {status}"))
            return
        if self._stop.is_set():
            return
        try:
            self._queue.put_nowait(bytes(indata))
        except queue.Full:
            self._fail(RuntimeError("microphone queue overflow"))

    def _fail(self, error: BaseException) -> None:
        if self._error is None:
            self._error = error
        self._stop.set()
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            pass

    def _next_item(self) -> bytes | None:
        while True:
            if self._error is not None:
                raise self._error
            try:
                item = self._queue.get(timeout=0.1)
            except queue.Empty:
                if self._stop.is_set():
                    return None
                continue
            if item is None:
                return None
            return item

    def blocks(self) -> Iterator[AudioBlock]:
        try:
            with self._stream_factory() as stream:
                self._stream = stream
                rate, channels = self._device_rate_and_channels()
                converter = self._converter_factory(rate, channels)
                offset = 0
                while True:
                    item = self._next_item()
                    if item is None:
                        break
                    samples = converter.convert(item)
                    if samples:
                        if self._gain != 1.0:
                            samples = [
                                _clamp(value * self._gain) for value in samples
                            ]
                        yield AudioBlock(samples=tuple(samples), start_sample=offset)
                        offset += len(samples)
                tail = converter.flush()
                if tail:
                    yield AudioBlock(samples=tuple(tail), start_sample=offset)
        except BaseException:
            self._stop.set()
            raise
        finally:
            self._stream = None

    def request_stop(self) -> None:
        if self._stop.is_set():
            return
        self._stop.set()
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            pass


__all__ = [
    "DEFAULT_BLOCKSIZE",
    "DEFAULT_GAIN",
    "DEFAULT_MAX_QUEUE",
    "MicrophoneSource",
    "SAMPLE_RATE",
    "WASAPI_NAME",
    "list_microphones",
]
