"""Unit tests for the Whisper recognizer's configuration checks."""

from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest import mock

from liebad.whisper_recognizer import MODEL_ENV, WhisperRecognizer, model_dir_from_env

try:  # discovery starts inside tests/unit, so the helper is importable directly
    from scratch import remove, scratch_dir
except ImportError:  # pragma: no cover - discovery from tests/
    from .scratch import remove, scratch_dir


def make_dir() -> Path:
    return scratch_dir("liebad-model")


class ModelDirFromEnvTest(unittest.TestCase):
    def test_missing_variable_is_explained(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(RuntimeError) as raised:
                model_dir_from_env()

        self.assertIn(MODEL_ENV, str(raised.exception))

    def test_directory_without_weights_is_rejected(self) -> None:
        folder = make_dir()
        self.addCleanup(remove, folder)

        with mock.patch.dict(os.environ, {MODEL_ENV: str(folder)}):
            with self.assertRaises(FileNotFoundError) as raised:
                model_dir_from_env()

        self.assertIn("model.bin", str(raised.exception))
        with self.assertRaises(FileNotFoundError):
            WhisperRecognizer(folder)


if __name__ == "__main__":
    unittest.main()
