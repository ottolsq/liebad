"""Unit tests for the recognition engine helpers."""

from __future__ import annotations

import os
import unittest
from pathlib import Path

from liebad.engines import (
    DEFAULT_WAV2VEC_DIR,
    ENGINE_HYBRID,
    ENGINE_LABELS,
    ENGINE_WAV2VEC,
    ENGINE_WHISPER,
    WAV2VEC_MODEL_ENV,
    normalize_engine,
    require_model_dir,
    wav2vec_model_dir,
)


class NormalizeEngineTest(unittest.TestCase):
    def test_missing_value_defaults_to_whisper(self) -> None:
        self.assertEqual(normalize_engine(None), ENGINE_WHISPER)
        self.assertEqual(normalize_engine(""), ENGINE_WHISPER)

    def test_known_names_are_case_and_space_insensitive(self) -> None:
        self.assertEqual(normalize_engine(" WAV2VEC "), ENGINE_WAV2VEC)
        self.assertEqual(normalize_engine("Whisper"), ENGINE_WHISPER)
        self.assertEqual(normalize_engine("Hybrid"), ENGINE_HYBRID)

    def test_every_engine_has_a_short_label(self) -> None:
        self.assertEqual(
            set(ENGINE_LABELS), {ENGINE_WHISPER, ENGINE_WAV2VEC, ENGINE_HYBRID}
        )

    def test_unknown_name_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            normalize_engine("vosk")


class Wav2VecDirTest(unittest.TestCase):
    def test_explicit_path_wins(self) -> None:
        self.assertEqual(
            wav2vec_model_dir(Path("models/custom")), Path("models/custom")
        )

    def test_environment_override(self) -> None:
        previous = os.environ.get(WAV2VEC_MODEL_ENV)
        os.environ[WAV2VEC_MODEL_ENV] = "temp/w2v"
        try:
            self.assertEqual(wav2vec_model_dir(), Path("temp/w2v"))
        finally:
            if previous is None:
                os.environ.pop(WAV2VEC_MODEL_ENV, None)
            else:
                os.environ[WAV2VEC_MODEL_ENV] = previous

    def test_default_is_the_bundled_checkpoint(self) -> None:
        previous = os.environ.pop(WAV2VEC_MODEL_ENV, None)
        try:
            self.assertEqual(wav2vec_model_dir(), DEFAULT_WAV2VEC_DIR)
        finally:
            if previous is not None:
                os.environ[WAV2VEC_MODEL_ENV] = previous

    def test_missing_directory_reports_the_path(self) -> None:
        with self.assertRaises(FileNotFoundError) as raised:
            require_model_dir(Path("models/does-not-exist"))
        self.assertIn("does-not-exist", str(raised.exception))

    def test_existing_directory_is_returned(self) -> None:
        self.assertEqual(require_model_dir(Path("src")), Path("src"))


if __name__ == "__main__":
    unittest.main()
