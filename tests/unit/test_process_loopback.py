"""Tests for the loopback source and the application catalog."""

from __future__ import annotations

import unittest
from itertools import islice

from liebad.audio.process_catalog import AppSource, _build_sources
from liebad.audio.process_loopback import ProcessLoopbackError, ProcessLoopbackSource
from liebad.contracts import FRAME_SAMPLES


class FakeClient:
    def __init__(self, packets=(), error=None):
        self._packets = [list(packet) for packet in packets]
        self._error = error
        self.opened = 0
        self.closed = 0

    def open(self):
        self.opened += 1

    def read_packets(self):
        if self._error is not None:
            raise self._error
        if self._packets:
            return [self._packets.pop(0)]
        return []

    def close(self):
        self.closed += 1


class FakeProbe:
    def __init__(self, alive=True):
        self._alive = alive
        self.closed = 0

    def alive(self):
        return self._alive

    def close(self):
        self.closed += 1


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def make_source(client, clock, probe=None, **kwargs):
    return ProcessLoopbackSource(
        4321,
        client_factory=lambda pid: client,
        process_probe=probe or FakeProbe(),
        clock=clock,
        sleep=clock.sleep,
        **kwargs,
    )


class LoopbackSourceTest(unittest.TestCase):
    def test_packets_are_forwarded_with_offsets_and_closed(self):
        clock = FakeClock()
        client = FakeClient([(1.0, -1.0), (0.5, 0.0, 0.25)])
        source = make_source(client, clock)
        blocks = list(islice(source.blocks(), 3))
        self.assertEqual(blocks[0].samples, (1.0, -1.0))
        self.assertEqual(blocks[0].start_sample, 0)
        self.assertEqual(blocks[1].samples, (0.5, 0.0, 0.25))
        self.assertEqual(blocks[1].start_sample, 2)
        self.assertEqual(blocks[2].start_sample, 5)
        self.assertTrue(client.closed)

    def test_gain_and_clipping_apply_to_packets(self):
        clock = FakeClock()
        client = FakeClient([(2.0, -3.0, 0.1)])
        source = make_source(client, clock, gain=6.0)
        block = next(iter(source.blocks()))
        self.assertEqual(block.samples[:2], (1.0, -1.0))
        self.assertAlmostEqual(block.samples[2], 0.6)

    def test_silence_is_padded_when_no_packets_arrive(self):
        clock = FakeClock()
        client = FakeClient([])
        source = make_source(client, clock, silence_gap=0.05)
        blocks = list(islice(source.blocks(), 2))
        self.assertEqual(blocks[0].samples, (0.0,) * FRAME_SAMPLES)
        self.assertEqual(blocks[0].start_sample, 0)
        self.assertEqual(blocks[1].start_sample, FRAME_SAMPLES)
        self.assertGreaterEqual(clock.now, 0.05)

    def test_process_exit_raises_and_closes(self):
        clock = FakeClock()
        client = FakeClient([])
        probe = FakeProbe(alive=False)
        source = make_source(client, clock, probe=probe)
        with self.assertRaises(ProcessLoopbackError):
            list(source.blocks())
        self.assertEqual(client.closed, 1)
        self.assertEqual(probe.closed, 1)

    def test_process_exit_is_detected_while_packets_keep_flowing(self):
        clock = FakeClock()
        client = FakeClient([(0.5, 0.5)] * 40)
        probe = FakeProbe(alive=True)
        source = make_source(client, clock, probe=probe, probe_interval=0.2)
        blocks = source.blocks()
        for _ in range(3):
            next(blocks)
        clock.now = 0.5
        probe._alive = False
        with self.assertRaises(ProcessLoopbackError):
            list(blocks)
        self.assertEqual(client.closed, 1)

    def test_client_failure_is_propagated_and_closed(self):
        clock = FakeClock()
        client = FakeClient(error=ProcessLoopbackError("activation failed"))
        source = make_source(client, clock)
        with self.assertRaises(ProcessLoopbackError):
            list(source.blocks())
        self.assertEqual(client.closed, 1)

    def test_request_stop_ends_iteration(self):
        clock = FakeClock()
        client = FakeClient([])
        source = make_source(client, clock, silence_gap=0.0)
        blocks = source.blocks()
        next(blocks)
        source.request_stop()
        self.assertEqual(list(blocks), [])
        self.assertEqual(client.closed, 1)


class AppCatalogTest(unittest.TestCase):
    def test_label_combines_process_and_window(self):
        source = AppSource(12, "chrome.exe", "示例 - Google Chrome")
        self.assertEqual(source.label, "chrome.exe · 示例 - Google Chrome")
        self.assertEqual(AppSource(13, "player.exe", "").label, "player.exe")

    def test_sources_are_deduplicated_by_process_keeping_longest_title(self):
        rows = [(1, "a"), (1, "longer title"), (2, "b"), (3, "")]
        names = {1: "one.exe", 2: "two.exe", 3: "three.exe"}
        sources = _build_sources(rows, names.__getitem__, exclude_pid=None)
        self.assertEqual([source.pid for source in sources], [1, 2])
        self.assertEqual(sources[0].window_title, "longer title")
        self.assertEqual(sources[0].process_name, "one.exe")

    def test_excluded_process_is_skipped(self):
        rows = [(1, "a"), (2, "b")]
        sources = _build_sources(rows, lambda pid: f"{pid}.exe", exclude_pid=2)
        self.assertEqual([source.pid for source in sources], [1])


if __name__ == "__main__":
    unittest.main()
