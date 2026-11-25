"""Tests for the ASR benchmark helpers."""

from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
import uuid
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import asr_bench  # noqa: E402
from liebad.replay_audio import ReplayAudioSource  # noqa: E402


def write_wav(path: Path, samples: list[int], rate: int = 16_000) -> None:
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(b"".join(int(value).to_bytes(2, "little", signed=True) for value in samples))


class ScoringTest(unittest.TestCase):
    def test_units_split_chinese_characters_from_latin_words(self) -> None:
        self.assertEqual(asr_bench.units("你好 API 调用"), ["你", "好", "api", "调", "用"])

    def test_normalize_folds_case_and_drops_punctuation(self) -> None:
        self.assertEqual(asr_bench.normalize("你好，API！  Call。"), "你好apicall")

    def test_score_counts_one_substitution(self) -> None:
        errors, total = asr_bench.score("楼市成交", "楼是成交")
        self.assertEqual((errors, total), (1, 4))

    def test_score_counts_missing_latin_word(self) -> None:
        errors, total = asr_bench.score("调用 API", "调用")
        self.assertEqual((errors, total), (1, 3))


class ReplayTest(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = Path(tempfile.gettempdir()) / f"liebad-bench-{uuid.uuid4().hex}"
        self.folder.mkdir()
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.wav = self.folder / "clip.wav"
        write_wav(self.wav, [1000] * 900)

    def test_blocks_advance_start_sample_and_stop(self) -> None:
        source = ReplayAudioSource(self.wav, clock=lambda: 0.0, sleep=lambda _: None)
        blocks = list(source.blocks())
        self.assertEqual([block.start_sample for block in blocks], [0, 320, 640])
        self.assertEqual(len(blocks[-1].samples), 260)

    def test_request_stop_ends_iteration(self) -> None:
        source = ReplayAudioSource(self.wav, clock=lambda: 0.0, sleep=lambda _: None)
        iterator = source.blocks()
        next(iterator)
        source.request_stop()
        self.assertEqual(list(iterator), [])

    def test_gain_scales_and_clamps(self) -> None:
        source = ReplayAudioSource(self.wav, gain=100.0, clock=lambda: 0.0, sleep=lambda _: None)
        block = next(source.blocks())
        self.assertAlmostEqual(max(block.samples), 1.0)
        self.assertAlmostEqual(min(block.samples), 1000 / 32_768 * 100 if 1000 / 32_768 * 100 < 1 else 1.0)

    def test_rejects_non_mono_or_wrong_rate(self) -> None:
        other = self.folder / "stereo.wav"
        with wave.open(str(other), "wb") as handle:
            handle.setnchannels(2)
            handle.setsampwidth(2)
            handle.setframerate(16_000)
            handle.writeframes(b"\x00\x00" * 20)
        with self.assertRaises(ValueError):
            list(ReplayAudioSource(other).blocks())

    def test_manifest_is_read_with_unicode(self) -> None:
        manifest = self.folder / "manifest.csv"
        manifest.write_text(
            "audio,reference,language,speechStartSeconds\n"
            "assets/a.wav,而对楼市,zh,0.52\n"
            "assets/b.wav,调用 API,mixed,1.68\n",
            encoding="utf-8",
        )
        samples = asr_bench.load_manifest(manifest)
        self.assertEqual([sample.language for sample in samples], ["zh", "mixed"])
        self.assertEqual(samples[1].speech_start, 1.68)


if __name__ == "__main__":
    unittest.main()
