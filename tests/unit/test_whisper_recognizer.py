"""Unit tests for the Whisper recognizer's configuration checks."""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest import mock

from liebad.whisper_recognizer import MODEL_ENV, WhisperRecognizer, model_dir_from_env


def make_dir() -> Path:
    folder = Path(tempfile.gettempdir()) / f"liebad-model-{uuid.uuid4().hex}"
    folder.mkdir()
    return folder


class ModelDirFromEnvTest(unittest.TestCase):
    def test_missing_variable_is_explained(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(RuntimeError) as raised:
                model_dir_from_env()

        self.assertIn(MODEL_ENV, str(raised.exception))

    def test_directory_without_weights_is_rejected(self) -> None:
        folder = make_dir()
        self.addCleanup(shutil.rmtree, folder, True)

        with mock.patch.dict(os.environ, {MODEL_ENV: str(folder)}):
            with self.assertRaises(FileNotFoundError) as raised:
                model_dir_from_env()

        self.assertIn("model.bin", str(raised.exception))
        with self.assertRaises(FileNotFoundError):
            WhisperRecognizer(folder)


if __name__ == "__main__":
    unittest.main()
