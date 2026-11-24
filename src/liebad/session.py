"""Drive a caption session from a stream of audio blocks.

The session runs on a background thread. It slices audio into 20 ms frames,
gates speech with an RMS threshold, asks the recognizer for provisional text
while a segment is open, freezes the prefix shared by consecutive results, and
finalizes a segment after a pause, at the maximum length, or when the source
drains. Provisional recognition runs on its own thread so that audio intake
never waits for the model; a newer provisional request for the same segment
replaces the queued one. All timing is derived from sample counts, never wall
clock.
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
    speech_samples: int = 0
    partial_at: int = 0
    fixed: str = ""
    last_result: str = ""
    closing: bool = False
    finalized: bool = False


def _common_prefix(left: str, right: str) -> str:
    limit = min(len(left), len(right))
    index = 0
    while index < limit and left[index] == right[index]:
        index += 1
    return left[:index]


def _freeze(fixed: str, last_result: str, text: str) -> tuple[str, str]:
    """Extend the frozen prefix and return ``(fixed, draft)``.

    The frozen part only ever grows: it is the common prefix of two
    consecutive results for the same segment. The draft is that prefix
    followed by whatever the latest result still leaves open.
    """

    if last_result:
        prefix = _common_prefix(last_result, text)
        if len(prefix) > len(fixed):
            fixed = prefix
    rest = text[len(fixed) :] if text.startswith(fixed) else text
    return fixed, fixed + rest


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
        partial_recognizer: SpeechRecognizer | None = None,
    ) -> None:
        self._source = source
        self._recognizer = recognizer
        self._partial_recognizer = partial_recognizer or recognizer
        self._publish_callback = publish
        self._options = options or CaptionOptions()
        self._partial_samples = max(
            1, self._options.partial_interval_ms * SAMPLE_RATE // 1000
        )
        self._pause_samples = self._options.pause_duration_ms * SAMPLE_RATE // 1000
        self._max_samples = self._options.max_segment_ms * SAMPLE_RATE // 1000
        self._min_speech_samples = self._options.min_speech_ms * SAMPLE_RATE // 1000

        self._lock = threading.Lock()
        self._recognize_lock = threading.Lock()
        self._partial_lock = self._recognize_lock if partial_recognizer is None else threading.Lock()
        self._partial_ready = threading.Condition()
        self._stop_event = threading.Event()
        self._stop_forwarded = False
        self._started = False

        self._state = CaptionState.CAPTURING
        self._draft = ""
        self._error: str | None = None
        self._finals: list[FinalCaption] = []
        self._snapshot = CaptionSnapshot(CaptionState.CAPTURING, "", ())

        self._frame_buffer: list[float] = []
        self._segment: _Segment | None = None
        self._next_index = 0

        self._partial_jobs: dict[int, list[float]] = {}
        self._inference: threading.Thread | None = None
        self._inference_stopped = False

        self._final_jobs: list[tuple[int, list[float]]] = []
        self._final_ready = threading.Condition()
        self._final_draining = False
        self._final_worker: threading.Thread | None = None

    def run(self) -> CaptionSnapshot:
        """Consume the whole source on a worker thread and return the final snapshot."""

        with self._lock:
            if self._started:
                raise RuntimeError("caption session already started")
            self._started = True
        if not self._stop_event.is_set():
            self._publish(CaptionState.CAPTURING, "")
        inference = threading.Thread(
            target=self._infer, name="liebad-caption-inference", daemon=True
        )
        self._inference = inference
        inference.start()
        final_worker = threading.Thread(
            target=self._recognize_finals, name="liebad-caption-final", daemon=True
        )
        self._final_worker = final_worker
        final_worker.start()
        worker = threading.Thread(
            target=self._consume, name="liebad-caption-session", daemon=True
        )
        worker.start()
        worker.join()
        with self._partial_ready:
            self._inference_stopped = True
            self._partial_ready.notify_all()
        with self._final_ready:
            self._final_draining = True
            self._final_ready.notify_all()
        inference.join()
        final_worker.join()
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

    # -- final recognition thread

    def _recognize_finals(self) -> None:
        while True:
            with self._final_ready:
                while not self._final_jobs and not self._final_draining:
                    self._final_ready.wait(timeout=0.1)
                if not self._final_jobs:
                    if self._final_draining:
                        return
                    continue
                index, audio = self._final_jobs.pop(0)

            with self._recognize_lock:
                text = self._recognizer.recognize(audio)
            if text:
                with self._lock:
                    self._finals.append(FinalCaption(segment_id=index, text=text))
                    self._finals.sort(key=lambda caption: caption.segment_id)
            self._publish(self._state, "")

    # -- provisional recognition thread

    def _infer(self) -> None:
        while True:
            with self._partial_ready:
                while not self._partial_jobs and not self._inference_stopped:
                    self._partial_ready.wait(timeout=0.1)
                if not self._partial_jobs:
                    if self._inference_stopped:
                        return
                    continue
                index = next(reversed(self._partial_jobs))
                audio = self._partial_jobs.pop(index)

            with self._partial_lock:
                with self._lock:
                    segment = self._segment
                    stale = (
                        segment is None
                        or segment.index != index
                        or segment.closing
                    )
                if stale:
                    continue
                text = self._partial_recognizer.recognize(audio)

            if segment is None or segment.index != index or segment.finalized:
                continue
            with self._lock:
                segment.fixed, draft = _freeze(
                    segment.fixed, segment.last_result, text
                )
                segment.last_result = text
                state = self._state
            self._publish(state, draft)

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
            segment.speech_samples += len(samples)
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
        with self._partial_ready:
            self._partial_jobs[segment.index] = list(segment.samples)
            self._partial_ready.notify()

    def _finalize(self, segment: _Segment | None, *, trim_silence: bool) -> None:
        if segment is None or segment.finalized or segment.closing:
            return
        segment.closing = True
        with self._partial_ready:
            self._partial_jobs.pop(segment.index, None)
        if segment.speech_samples < self._min_speech_samples:
            # A blip of noise must not become a hallucinated caption.
            with self._lock:
                if self._segment is segment:
                    self._segment = None
            segment.finalized = True
            self._publish(self._state, "")
            return
        if trim_silence:
            keep = len(segment.samples) - segment.silence_samples
            audio = list(segment.samples[:keep]) if keep > 0 else []
        else:
            audio = list(segment.samples)
        with self._lock:
            if self._segment is segment:
                self._segment = None
        segment.finalized = True
        if not audio:
            self._publish(self._state, "")
            return
        with self._final_ready:
            self._final_jobs.append((segment.index, audio))
            self._final_ready.notify()
        # Keep the frozen draft on screen until the final text replaces it.
        self._publish(self._state, self._draft)

    def _publish(
        self, state: CaptionState, draft: str, error: str | None = None
    ) -> None:
        with self._lock:
            # Trailing publishes from the finishing threads must not wipe the
            # failure that ended the session.
            if state is CaptionState.FAULTED:
                self._error = error or self._error
            else:
                self._error = None
            self._state = state
            self._draft = draft
            snapshot = CaptionSnapshot(
                state=state,
                draft=draft,
                final=tuple(self._finals),
                error=self._error if state is CaptionState.FAULTED else None,
            )
            self._snapshot = snapshot
        self._publish_callback(snapshot)
