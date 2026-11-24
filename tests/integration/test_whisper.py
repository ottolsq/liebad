"""Integration check: the real Whisper model decodes a recorded window.

Opt in with three environment variables so the default unit run stays fast and
free of model loading:

    LIEBAD_TEST_MODEL    local CTranslate2 Whisper directory (models\\faster-whisper-small)
    LIEBAD_TEST_WAV      16 kHz mono 16-bit WAV with known Chinese speech
    LIEBAD_TEST_KEYWORD  a word the transcript must contain (spaces are ignored)
"""

from __future__ import annotations

import os
import unittest
import wave
from pathlib import Path

import numpy as np

from liebad.whisper_recognizer import WhisperRecognizer

REQUIRED_ENV = ("LIEBAD_TEST_MODEL", "LIEBAD_TEST_WAV", "LIEBAD_TEST_KEYWORD")


def read_mono_wav(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as handle:
        if handle.getframerate() != 16_000 or handle.getnchannels() != 1:
            raise AssertionError(
                f"{path} must be 16 kHz mono, got {handle.getframerate()} Hz"
                f" {handle.getnchannels()} channel(s)"
            )
        if handle.getsampwidth() != 2:
            raise AssertionError(f"{path} must be 16-bit PCM")
        frames = handle.readframes(handle.getnframes())
    return np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0


def normalize(samples: np.ndarray, target_peak: float = 0.3) -> np.ndarray:
    """Lift quiet material to the peak the validated decode assumes.

    The reference recording peaks at 0.02 (about -34 dBFS) and the model
    mis-hears several words at that level; the same window scaled to 0.3,
    which is what the test records call gain 15, decodes correctly.
    """

    peak = float(np.abs(samples).max()) if samples.size else 0.0
    if peak == 0.0:
        return samples
    return np.clip(samples * (target_peak / peak), -1.0, 1.0).astype(np.float32)


class WhisperRecognizerIntegrationTest(unittest.TestCase):
    def test_recorded_window_contains_reference_keyword(self) -> None:
        values = {name: os.environ.get(name) for name in REQUIRED_ENV}
        missing = [name for name, value in values.items() if not value]
        if missing:
            self.skipTest("missing " + ", ".join(missing))

        samples = normalize(read_mono_wav(Path(values["LIEBAD_TEST_WAV"])))
        recognizer = WhisperRecognizer(Path(values["LIEBAD_TEST_MODEL"]))

        text = recognizer.recognize(samples)

        self.assertTrue(text, "empty transcript")
        self.assertIn(values["LIEBAD_TEST_KEYWORD"], "".join(text.split()))


if __name__ == "__main__":
    unittest.main()
