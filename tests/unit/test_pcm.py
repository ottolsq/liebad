"""Unit tests for the PCM converter shared by every audio source."""

from __future__ import annotations

import unittest

import numpy as np

from liebad.audio.pcm import Pcm16kConverter

RATE = 48_000


def stereo_pcm(seconds: float = 1.0, amplitude: float = 0.4) -> bytes:
    t = np.arange(int(RATE * seconds)) / RATE
    mono = amplitude * np.sin(2 * np.pi * 440 * t)
    stereo = np.stack([mono, mono], axis=1)
    return (stereo * 32767).astype(np.int16).tobytes()


def convert_whole(data: bytes, channels: int = 2) -> list[float]:
    converter = Pcm16kConverter(RATE, channels)
    return list(converter.convert(data)) + list(converter.flush())


def convert_chunked(data: bytes, chunk_bytes: int, channels: int = 2) -> list[float]:
    converter = Pcm16kConverter(RATE, channels)
    out: list[float] = []
    for start in range(0, len(data), chunk_bytes):
        out.extend(converter.convert(data[start : start + chunk_bytes]))
    out.extend(converter.flush())
    return out


def crossings(values: list[float]) -> int:
    arr = np.asarray(values)
    return int(np.sum(np.signbit(arr[:-1]) != np.signbit(arr[1:])))


class Pcm16kConverterTest(unittest.TestCase):
    def test_one_second_of_48k_stereo_becomes_16k_mono(self) -> None:
        out = convert_whole(stereo_pcm())

        self.assertEqual(len(out), 16_000)
        self.assertAlmostEqual(max(out), 0.4 * np.sqrt(2), delta=0.02)
        self.assertTrue(870 <= crossings(out) <= 890)

    def test_chunked_conversion_matches_whole_conversion(self) -> None:
        data = stereo_pcm()
        whole = convert_whole(data)

        for chunk_bytes in (3840, 960, 240, 7):
            with self.subTest(chunk_bytes=chunk_bytes):
                chunked = convert_chunked(data, chunk_bytes)
                self.assertEqual(len(chunked), len(whole))
                self.assertEqual(max(abs(a - b) for a, b in zip(whole, chunked)), 0.0)

    def test_mono_input_is_resampled_without_duplication(self) -> None:
        t = np.arange(RATE) / RATE
        data = (0.4 * np.sin(2 * np.pi * 440 * t) * 32767).astype(np.int16).tobytes()

        out = convert_whole(data, channels=1)

        self.assertEqual(len(out), 16_000)
        self.assertAlmostEqual(max(out), 0.4, delta=0.02)

    def test_unknown_format_or_channel_count_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            Pcm16kConverter(RATE, 2, sample_format="s24")
        with self.assertRaises(ValueError):
            Pcm16kConverter(RATE, 3)

    def test_flush_keeps_the_filter_tail_and_closes_the_converter(self) -> None:
        converter = Pcm16kConverter(RATE, 2)
        produced = list(converter.convert(stereo_pcm(0.1)))

        tail = list(converter.flush())

        self.assertEqual(len(produced) + len(tail), 1600)
        self.assertEqual(converter.flush(), [])
        with self.assertRaises(RuntimeError):
            converter.convert(b"\x00\x00\x00\x00")


if __name__ == "__main__":
    unittest.main()
