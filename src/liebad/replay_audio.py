"""Replay a WAV file as a real-time audio source."""

from __future__ import annotations

import threading
import time
import wave
from pathlib import Path
from typing import Iterator, Sequence

from liebad.contracts import FRAME_SAMPLES, SAMPLE_RATE, AudioBlock


class ReplayAudioSource:
    """Deliver a 16 kHz mono 16-bit WAV in real time, block by block."""

    def __init__(
        self,
        wav_path: Path,
        *,
        gain: float = 1.0,
        speed: float = 1.0,
        clock=time.monotonic,
        sleep=time.sleep,
    ) -> None:
        if speed <= 0:
            raise ValueError("speed must be positive")
        self._path = Path(wav_path)
        self._gain = gain
        self._speed = speed
        self._clock = clock
        self._sleep = sleep
        self._stop = threading.Event()

    @property
    def path(self) -> Path:
        return self._path

    @property
    def stop_requested(self) -> bool:
        return self._stop.is_set()

    def request_stop(self) -> None:
        self._stop.set()

    def read_samples(self) -> Sequence[float]:
        with wave.open(str(self._path), "rb") as handle:
            if handle.getframerate() != SAMPLE_RATE:
                raise ValueError(f"{self._path} must be {SAMPLE_RATE} Hz")
            if handle.getnchannels() != 1 or handle.getsampwidth() != 2:
                raise ValueError(f"{self._path} must be mono 16-bit")
            raw = handle.readframes(handle.getnframes())
        values = tuple(value / 32_768.0 for value in memoryview(raw).cast("h"))
        if self._gain == 1.0:
            return values
        return tuple(max(-1.0, min(1.0, value * self._gain)) for value in values)

    def blocks(self) -> Iterator[AudioBlock]:
        samples = self.read_samples()
        started = self._clock()
        offset = 0
        while offset < len(samples):
            if self._stop.is_set():
                return
            chunk = samples[offset : offset + FRAME_SAMPLES]
            deadline = started + offset / SAMPLE_RATE / self._speed
            delay = deadline - self._clock()
            if delay > 0:
                self._sleep(delay)
            yield AudioBlock(samples=chunk, start_sample=offset)
            offset += len(chunk)


__all__ = ["ReplayAudioSource"]
