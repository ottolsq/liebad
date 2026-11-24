"""Drive a caption session from a stream of audio blocks.

The session runs on a background thread. It slices audio into 20 ms frames,
gates speech with an RMS threshold, asks the recognizer for provisional text
while a segment is open, freezes the prefix shared by two consecutive results,
and finalizes a segment after a pause, at the maximum length, or when the
source drains. All timing is derived from sample counts, never wall clock.
"""

from __future__ import annotations

import math
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from .contracts import (
    FRAME_SAMPLES,
    SAMPLE_RATE,
    AudioSource,
    CaptionOptions,
    CaptionSnapshot,
    CaptionState,
    FinalCaption,
    SpeechRecognizer,
)


@dataclass
class _Segment:
    """Audio and provisional state for one caption segment."""

    index: int
    samples: list[float] = field(default_factory=list)
    silence_samples: int = 0
    partial_at: int = 0
    fixed: str = ""
    last_result: str = ""
    finalized: bool = False


def _common_prefix(left: str, right: str) -> str:
    limit = min(len(left), len(right))
    index = 0
    while index < limit and left[index] == right[index]:
        index += 1
    return left[:index]


def _rms(frame: Sequence[float]) -> float:
    total = 0.0
    for value in frame:
        total += value * value
    return math.sqrt(total / len(frame))


class CaptionSession:
    """Turn audio blocks into provisional and final captions."""

    def __init__(
        self,
        source: AudioSource,
        recognizer: SpeechRecognizer,
        publish: Callable[[CaptionSnapshot], None],
        options: CaptionOptions | None = None,
    ) -> None:
        self._source = source
        self._recognizer = recognizer
        self._publish_callback = publish
        self._options = options or CaptionOptions()
        self._partial_samples = max(
            1, self._options.partial_interval_ms * SAMPLE_RATE // 1000
        )
        self._pause_samples = self._options.pause_duration_ms * SAMPLE_RATE // 1000
        self._max_samples = self._options.max_segment_ms * SAMPLE_RATE // 1000

        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._stop_forwarded = False
        self._started = False

        self._state = CaptionState.CAPTURING
        self._draft = ""
        self._finals: list[FinalCaption] = []
        self._snapshot = CaptionSnapshot(CaptionState.CAPTURING, "", ())

        self._frame_buffer: list[float] = []
        self._segment: _Segment | None = None
        self._next_index = 0

    def run(self) -> CaptionSnapshot:
        """Consume the whole source on a worker thread and return the final snapshot."""

        with self._lock:
            if self._started:
                raise RuntimeError("caption session already started")
            self._started = True
        if not self._stop_event.is_set():
            self._publish(CaptionState.CAPTURING, "")
        worker = threading.Thread(
            target=self._consume, name="liebad-caption-session", daemon=True
        )
        worker.start()
        worker.join()
        return self._snapshot

    def request_stop(self) -> None:
        """Ask the source to stop once; safe to call repeatedly from any thread."""

        with self._lock:
            if self._stop_forwarded:
                return
            self._stop_forwarded = True
            publish_finishing = self._state is CaptionState.CAPTURING
        self._stop_event.set()
        if publish_finishing:
            self._publish(CaptionState.FINISHING, self._draft)
        self._source.request_stop()

    # -- worker thread

    def _consume(self) -> None:
        try:
            for block in self._source.blocks():
                self._feed(block.samples)
            self._flush_tail()
            self._finalize(self._segment, trim_silence=True)
        except Exception as exc:  # noqa: BLE001 - surfaced through the snapshot
            self._publish(
                CaptionState.FAULTED, "", error=f"{type(exc).__name__}: {exc}"
            )
            return
        self._publish(CaptionState.COMPLETED, "")

    def _feed(self, samples: Sequence[float]) -> None:
        if not samples:
            return
        buffer = self._frame_buffer
        buffer.extend(samples)
        while len(buffer) >= FRAME_SAMPLES:
            frame = buffer[:FRAME_SAMPLES]
            del buffer[:FRAME_SAMPLES]
            self._handle_frame(frame)

    def _flush_tail(self) -> None:
        """Fold the last short frame into the open segment before finalizing.

        ``_feed`` only dispatches whole frames, so up to ``FRAME_SAMPLES - 1``
        samples can be left over when the source drains. They still belong to
        the last utterance and must reach the recognizer exactly once.
        """

        tail = self._frame_buffer
        self._frame_buffer = []
        if not tail:
            return
        speech = _rms(tail) >= self._options.speech_rms_threshold
        segment = self._segment
        if segment is None:
            if not speech:
                return
            segment = self._open_segment()
        self._extend(segment, tail, speech=speech)

    def _open_segment(self) -> _Segment:
        segment = _Segment(index=self._next_index)
        self._next_index += 1
        self._segment = segment
        return segment

    def _extend(
        self, segment: _Segment, samples: Sequence[float], *, speech: bool
    ) -> None:
        segment.samples.extend(samples)
        if speech:
            segment.silence_samples = 0
        else:
            segment.silence_samples += len(samples)

    def _handle_frame(self, frame: Sequence[float]) -> None:
        speech = _rms(frame) >= self._options.speech_rms_threshold
        segment = self._segment
        if segment is None:
            if not speech:
                return
            segment = self._open_segment()

        self._extend(segment, frame, speech=speech)

        if segment.silence_samples >= self._pause_samples:
            self._finalize(segment, trim_silence=True)
            return
        if len(segment.samples) >= self._max_samples:
            self._finalize(segment, trim_silence=False)
            return
        if self._stop_event.is_set():
            return
        if len(segment.samples) - segment.partial_at >= self._partial_samples:
            self._update_partial(segment)

    def _update_partial(self, segment: _Segment) -> None:
        segment.partial_at = len(segment.samples)
        text = self._recognizer.recognize(list(segment.samples))
        if segment.last_result:
            prefix = _common_prefix(segment.last_result, text)
            if len(prefix) > len(segment.fixed):
                segment.fixed = prefix
        segment.last_result = text
        fixed = segment.fixed
        rest = text[len(fixed) :] if text.startswith(fixed) else text
        self._publish(self._state, fixed + rest)

    def _finalize(self, segment: _Segment | None, *, trim_silence: bool) -> None:
        if segment is None or segment.finalized:
            return
        segment.finalized = True
        if trim_silence:
            keep = len(segment.samples) - segment.silence_samples
            audio = list(segment.samples[:keep]) if keep > 0 else []
        else:
            audio = list(segment.samples)
        self._segment = None
        if not audio:
            self._publish(self._state, "")
            return
        text = self._recognizer.recognize(audio)
        self._finals.append(FinalCaption(segment_id=segment.index, text=text))
        self._publish(self._state, "")

    def _publish(
        self, state: CaptionState, draft: str, error: str | None = None
    ) -> None:
        snapshot = CaptionSnapshot(
            state=state, draft=draft, final=tuple(self._finals), error=error
        )
        self._state = state
        self._draft = draft
        self._snapshot = snapshot
        self._publish_callback(snapshot)
