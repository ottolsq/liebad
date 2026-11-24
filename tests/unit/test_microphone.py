"""Unit tests for the microphone source, driven through an injected stream."""

from __future__ import annotations

import unittest

import numpy as np

from liebad.audio.microphone import MicrophoneSource

RATE = 48_000


def pcm_chunk(frames: int = 1024) -> bytes:
    t = np.arange(frames) / RATE
    return (0.3 * np.sin(2 * np.pi * 440 * t) * 32767).astype(np.int16).tobytes()


class SilentStream:
    """Stand-in for ``sd.RawInputStream``; the test feeds audio by hand."""

    def __init__(self) -> None:
        self.exited = False

    def __enter__(self) -> "SilentStream":
        return self

    def __exit__(self, *exc_info: object) -> bool:
        self.exited = True
        return False


def make_source(**kwargs: object) -> tuple[MicrophoneSource, SilentStream]:
    stream = SilentStream()
    source = MicrophoneSource(
        18,
        sample_rate=RATE,
        channels=1,
        blocksize=1024,
        stream_factory=lambda: stream,
        **kwargs,
    )
    return source, stream


class MicrophoneSourceTest(unittest.TestCase):
    def test_queued_capture_is_converted_then_drained(self) -> None:
        source, stream = make_source()
        chunk = pcm_chunk()
        for _ in range(10):
            source._callback(chunk, 1024, None, None)
        source.request_stop()

        blocks = list(source.blocks())

        total = sum(len(block.samples) for block in blocks)
        self.assertTrue(3412 <= total <= 3414, total)
        offsets = [block.start_sample for block in blocks]
        self.assertEqual(offsets[0], 0)
        self.assertEqual(offsets, sorted(offsets))
        self.assertTrue(stream.exited)

    def test_device_status_is_raised_to_the_consumer(self) -> None:
        source, _stream = make_source()
        source._callback(pcm_chunk(), 1024, None, None)
        source._callback(b"", 0, None, "input overflow")

        with self.assertRaises(RuntimeError) as raised:
            list(source.blocks())

        self.assertIn("input overflow", str(raised.exception))

    def test_queue_overflow_is_reported(self) -> None:
        source, _stream = make_source(max_queue=1)
        chunk = pcm_chunk()
        source._callback(chunk, 1024, None, None)
        source._callback(chunk, 1024, None, None)

        with self.assertRaises(RuntimeError) as raised:
            list(source.blocks())

        self.assertIn("queue overflow", str(raised.exception))

    def test_stop_before_start_ends_without_audio(self) -> None:
        source, stream = make_source()
        source.request_stop()

        self.assertEqual(list(source.blocks()), [])
        self.assertTrue(stream.exited)


if __name__ == "__main__":
    unittest.main()
