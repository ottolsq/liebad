"""Convert interleaved capture PCM into the 16 kHz mono float signal Whisper wants."""

from __future__ import annotations

from collections.abc import Sequence

from av import AudioFrame
from av.audio.resampler import AudioResampler

from ..contracts import SAMPLE_RATE

#: Bytes per sample for the raw formats a WASAPI capture can produce.
_BYTES_PER_SAMPLE = {"s16": 2, "flt": 4, "s32": 4}

#: PyAV layout names for the channel counts the prototype supports.
_LAYOUTS = {1: "mono", 2: "stereo"}


class Pcm16kConverter:
    """Stateful resampler for one capture stream.

    Keep one instance per stream: the resampler carries filter history across
    chunks, which is what keeps block boundaries seamless. Call :meth:`flush`
    once after the last chunk to collect the samples still inside the filter.
    """

    def __init__(
        self, sample_rate: int, channels: int, sample_format: str = "s16"
    ) -> None:
        if sample_rate <= 0:
            raise ValueError(f"invalid sample rate: {sample_rate}")
        if channels not in _LAYOUTS:
            raise ValueError(f"unsupported channel count: {channels}")
        if sample_format not in _BYTES_PER_SAMPLE:
            raise ValueError(f"unsupported sample format: {sample_format}")

        self._sample_rate = sample_rate
        self._format = sample_format
        self._layout = _LAYOUTS[channels]
        self._block_align = _BYTES_PER_SAMPLE[sample_format] * channels
        self._resampler = AudioResampler(format="flt", layout="mono", rate=SAMPLE_RATE)
        self._pending = bytearray()
        self._pts = 0
        self._flushed = False

    def convert(self, data: bytes) -> Sequence[float]:
        """Resample a chunk of interleaved PCM, carrying partial samples over."""

        if self._flushed:
            raise RuntimeError("converter already flushed")
        self._pending.extend(data)
        usable = len(self._pending) - len(self._pending) % self._block_align
        if usable == 0:
            return []
        payload = bytes(self._pending[:usable])
        del self._pending[:usable]
        return self._resample(payload, usable // self._block_align)

    def flush(self) -> Sequence[float]:
        """Return the samples still buffered by the resampler; call once."""

        if self._flushed:
            return []
        self._flushed = True
        self._pending.clear()
        samples: list[float] = []
        for frame in self._resampler.resample(None):
            samples.extend(_to_floats(frame))
        return samples

    def _resample(self, payload: bytes, count: int) -> Sequence[float]:
        frame = AudioFrame(format=self._format, layout=self._layout, samples=count)
        frame.sample_rate = self._sample_rate
        frame.pts = self._pts
        self._pts += count
        frame.planes[0].update(payload)
        samples: list[float] = []
        for chunk in self._resampler.resample(frame):
            samples.extend(_to_floats(chunk))
        return samples


def _to_floats(frame: AudioFrame) -> list[float]:
    return frame.to_ndarray().reshape(-1).tolist()
