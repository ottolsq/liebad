"""Unit tests for caption segmentation, prefix freezing and stop handling."""

from __future__ import annotations

import queue
import threading
import time
import unittest

from liebad.contracts import (
    SAMPLE_RATE,
    AudioBlock,
    CaptionOptions,
    CaptionState,
    FinalCaption,
)
from liebad.session import CaptionSession, _freeze

FRAME_SAMPLES = SAMPLE_RATE // 50  # 20 ms at 16 kHz


def speech(seconds: float, amplitude: float = 0.3) -> list[float]:
    return [amplitude] * int(SAMPLE_RATE * seconds)


def silence(seconds: float) -> list[float]:
    return [0.0] * int(SAMPLE_RATE * seconds)


class ListSource:
    """Yield pre-recorded blocks, then end."""

    def __init__(self, blocks: list[list[float]], pace: float = 0.0) -> None:
        self._blocks = list(blocks)
        self._pace = pace
        self.stop_calls = 0

    def blocks(self):
        for index, samples in enumerate(self._blocks):
            yield AudioBlock(samples=tuple(samples), start_sample=index * SAMPLE_RATE)
            if self._pace:
                time.sleep(self._pace)

    def request_stop(self) -> None:
        self.stop_calls += 1


class QueueSource:
    """Deliver pushed blocks from another thread; close on stop."""

    def __init__(self) -> None:
        self._queue: queue.Queue = queue.Queue()
        self.stop_calls = 0

    def push(self, samples: list[float], start_sample: int = 0) -> None:
        self._queue.put(AudioBlock(samples=tuple(samples), start_sample=start_sample))

    def blocks(self):
        while True:
            block = self._queue.get()
            if block is None:
                return
            yield block

    def request_stop(self) -> None:
        self.stop_calls += 1
        self._queue.put(None)


class ScriptedRecognizer:
    """Return scripted results in order; ``marker`` wins when the tail is present."""

    def __init__(self, results: list[str], marker: str | None = None) -> None:
        self._results = list(results)
        self._marker = marker
        self.calls: list[int] = []

    def recognize(self, mono16k) -> str:
        self.calls.append(len(mono16k))
        if self._marker is not None and any(sample > 0.4 for sample in mono16k):
            return self._marker
        if len(self._results) > 1:
            return self._results.pop(0)
        return self._results[0] if self._results else ""


class BrokenSource:
    def blocks(self):
        raise RuntimeError("device gone")

    def request_stop(self) -> None:
        pass


class Sink:
    def __init__(self) -> None:
        self.snapshots: list = []

    def __call__(self, snapshot) -> None:
        self.snapshots.append(snapshot)

    @property
    def drafts(self) -> list[str]:
        return [snapshot.draft for snapshot in self.snapshots]

    @property
    def states(self) -> list[CaptionState]:
        return [snapshot.state for snapshot in self.snapshots]


class SlowRecognizer:
    """Spend a fixed time per call so intake stalls become measurable."""

    def __init__(self, text: str, delay: float) -> None:
        self._text = text
        self._delay = delay
        self.calls = 0

    def recognize(self, mono16k) -> str:
        self.calls += 1
        time.sleep(self._delay)
        return self._text


class FreezeTest(unittest.TestCase):
    def test_common_prefix_grows_and_never_shrinks(self):
        fixed, draft = _freeze("", "", "今天去上")
        self.assertEqual((fixed, draft), ("", "今天去上"))

        fixed, draft = _freeze(fixed, "今天去上", "今天去上海")
        self.assertEqual((fixed, draft), ("今天去上", "今天去上海"))

        fixed, draft = _freeze(fixed, "今天去上海", "明天去上海")
        self.assertEqual(fixed, "今天去上")
        self.assertEqual(draft, "今天去上明天去上海")

        fixed, draft = _freeze(fixed, "明天去上海", "明天去上海吧")
        self.assertEqual(fixed, "明天去上海")
        self.assertEqual(draft, "明天去上海吧")


class CaptionSessionTest(unittest.TestCase):
    def make_session(self, source, recognizer, options=None, partial_recognizer=None):
        sink = Sink()
        session = CaptionSession(
            source, recognizer, sink, options, partial_recognizer=partial_recognizer
        )
        return session, sink

    def test_partial_recognizer_drafts_while_final_keeps_main_model(self):
        frames = [speech(0.02)] * 15 + [silence(0.02)] * 8
        source = ListSource(frames, pace=0.01)
        finals = ScriptedRecognizer(["定稿"])
        partial = ScriptedRecognizer(["草稿"])
        options = CaptionOptions(partial_interval_ms=50, pause_duration_ms=100)
        session, sink = self.make_session(
            source, finals, options, partial_recognizer=partial
        )
        snapshot = session.run()
        self.assertEqual(snapshot.final, (FinalCaption(0, "定稿"),))
        self.assertIn("草稿", sink.drafts)
        self.assertGreater(len(partial.calls), 0)
        self.assertEqual(len(finals.calls), 1)

    def test_provisional_recognition_does_not_stall_intake(self):
        recognizer = SlowRecognizer("今天去上", delay=0.3)
        source = ListSource([speech(4.0)])
        session, _ = self.make_session(source, recognizer)

        started = time.monotonic()
        snapshot = session.run()
        elapsed = time.monotonic() - started

        self.assertEqual(snapshot.state, CaptionState.COMPLETED)
        self.assertEqual(snapshot.final, (FinalCaption(0, "今天去上"),))
        self.assertLess(elapsed, 1.5)

    def test_stop_drains_audio_and_finalizes_once(self):
        recognizer = ScriptedRecognizer(["安静"], marker="尾音")
        source = QueueSource()
        session, sink = self.make_session(source, recognizer)
        result: dict = {}

        def target() -> None:
            result["snapshot"] = session.run()

        worker = threading.Thread(target=target)
        worker.start()
        source.push(speech(0.6), start_sample=0)
        source.push([0.5] * FRAME_SAMPLES, start_sample=int(SAMPLE_RATE * 0.6))
        session.request_stop()
        session.request_stop()
        worker.join(timeout=5)

        self.assertFalse(worker.is_alive())
        self.assertEqual(source.stop_calls, 1)
        snapshot = result["snapshot"]
        self.assertEqual(snapshot.state, CaptionState.COMPLETED)
        self.assertEqual(snapshot.draft, "")
        self.assertEqual(snapshot.final, (FinalCaption(0, "尾音"),))
        self.assertEqual(recognizer.calls[-1], int(SAMPLE_RATE * 0.6) + FRAME_SAMPLES)
        self.assertIn(CaptionState.FINISHING, sink.states)

    def test_subframe_tail_reaches_recognizer_after_stop(self):
        tail = [0.5] * 100
        recognizer = ScriptedRecognizer(["安静"], marker="尾音")
        source = ListSource([[0.3] * (SAMPLE_RATE // 2), tail])
        session, _ = self.make_session(source, recognizer)

        snapshot = session.run()

        self.assertEqual(snapshot.state, CaptionState.COMPLETED)
        self.assertEqual(snapshot.final, (FinalCaption(0, "尾音"),))
        self.assertEqual(recognizer.calls[-1], SAMPLE_RATE // 2 + len(tail))

    def test_stop_finalizes_subframe_audio_once(self):
        recognizer = ScriptedRecognizer(["安静"], marker="尾音")
        samples = [0.5] * 5_000  # 15 full frames plus a 200-sample tail
        source = ListSource([samples])
        session, _ = self.make_session(source, recognizer)

        snapshot = session.run()

        self.assertEqual(snapshot.state, CaptionState.COMPLETED)
        self.assertEqual(snapshot.final, (FinalCaption(0, "尾音"),))
        self.assertEqual(recognizer.calls, [5_000])

    def test_repeated_text_in_separate_segments_is_kept(self):
        recognizer = ScriptedRecognizer(["同一句"])
        source = ListSource([speech(0.5), silence(1.0), speech(0.5), silence(0.8)])
        session, _ = self.make_session(source, recognizer)

        snapshot = session.run()

        self.assertEqual(
            snapshot.final,
            (FinalCaption(0, "同一句"), FinalCaption(1, "同一句")),
        )

    def test_silence_never_calls_recognizer(self):
        recognizer = ScriptedRecognizer(["不该出现"])
        source = ListSource([silence(2.0)])
        session, sink = self.make_session(source, recognizer)

        snapshot = session.run()

        self.assertEqual(recognizer.calls, [])
        self.assertEqual(snapshot.final, ())
        self.assertEqual(snapshot.state, CaptionState.COMPLETED)
        self.assertEqual(set(sink.drafts), {""})

    def test_noise_blip_does_not_become_a_caption(self):
        recognizer = ScriptedRecognizer(["字幕by索兰娅"])
        source = ListSource([speech(0.02), silence(1.2)])
        session, _ = self.make_session(source, recognizer)

        snapshot = session.run()

        self.assertEqual(recognizer.calls, [])
        self.assertEqual(snapshot.final, ())

    def test_continuous_speech_splits_at_max_segment(self):
        recognizer = ScriptedRecognizer(["连续"])
        source = ListSource([speech(13.0)])
        options = CaptionOptions(max_segment_ms=12_000)
        session, _ = self.make_session(source, recognizer, options)

        snapshot = session.run()

        self.assertEqual([caption.segment_id for caption in snapshot.final], [0, 1])
        self.assertEqual(snapshot.final[0].text, "连续")

    def test_published_snapshots_are_independent(self):
        recognizer = ScriptedRecognizer(["甲"])
        source = ListSource([speech(0.5), silence(1.0), speech(0.5), silence(0.8)])
        session, sink = self.make_session(source, recognizer)

        session.run()

        first_with_one = next(
            snapshot for snapshot in sink.snapshots if len(snapshot.final) == 1
        )
        self.assertIsInstance(first_with_one.final, tuple)
        self.assertEqual(len(first_with_one.final), 1)
        self.assertEqual(len(sink.snapshots[-1].final), 2)
        self.assertEqual(len(first_with_one.final), 1)

    def test_source_failure_publishes_faulted(self):
        recognizer = ScriptedRecognizer(["x"])
        session, _ = self.make_session(BrokenSource(), recognizer)

        snapshot = session.run()

        self.assertEqual(snapshot.state, CaptionState.FAULTED)
        self.assertIn("device gone", snapshot.error or "")
        self.assertEqual(snapshot.draft, "")

    def test_fault_error_survives_the_finishing_threads(self):
        class SpeechThenBroken:
            def blocks(self):
                yield AudioBlock(samples=tuple(speech(1.0)), start_sample=0)
                raise RuntimeError("process exited")

            def request_stop(self) -> None:
                pass

        recognizer = ScriptedRecognizer(["第一段"])
        session, _ = self.make_session(SpeechThenBroken(), recognizer)

        snapshot = session.run()

        self.assertEqual(snapshot.state, CaptionState.FAULTED)
        self.assertIn("process exited", snapshot.error or "")
        self.assertEqual(snapshot.final, ())


if __name__ == "__main__":
    unittest.main()
