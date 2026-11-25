"""Tests for the overlay's remembered choices."""

from __future__ import annotations

import contextlib
import os
import tempfile
import unittest
import uuid
from pathlib import Path

from PySide6.QtCore import QSettings

from liebad.engines import (
    DEFAULT_WAV2VEC_DIR,
    ENGINE_HYBRID,
    ENGINE_WAV2VEC,
    ENGINE_WHISPER,
    WAV2VEC_MODEL_ENV,
)
from liebad.ui.settings import (
    DEFAULT_WHISPER_MODEL,
    KIND_APPLICATION,
    KIND_MICROPHONE,
    MODEL_ENV,
    OverlaySettings,
    resolve_wav2vec_model,
    resolve_whisper_model,
)


@contextlib.contextmanager
def environment(**values: str | None):
    """Temporarily set (or clear, with ``None``) environment variables."""

    saved = {name: os.environ.get(name) for name in values}
    for name, value in values.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value
    try:
        yield
    finally:
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


class OverlaySettingsTest(unittest.TestCase):
    def setUp(self) -> None:
        folder = Path(tempfile.gettempdir()) / f"liebad-settings-{uuid.uuid4().hex}"
        folder.mkdir()
        self.addCleanup(lambda: __import__("shutil").rmtree(folder, True))
        self.path = folder / "overlay.ini"
        self.settings = OverlaySettings(self.path)

    def test_defaults_when_nothing_is_stored(self) -> None:
        self.assertEqual(self.settings.engine, ENGINE_WHISPER)
        self.assertEqual(self.settings.kind, KIND_MICROPHONE)
        self.assertIsNone(self.settings.microphone)
        self.assertIsNone(self.settings.application)
        self.assertIsNone(self.settings.whisper_model)
        self.assertIsNone(self.settings.wav2vec_model)

    def test_engine_round_trip(self) -> None:
        self.settings.engine = ENGINE_HYBRID
        self.assertEqual(self.settings.engine, ENGINE_HYBRID)

    def test_unknown_engine_falls_back_to_whisper(self) -> None:
        QSettings(str(self.path), QSettings.Format.IniFormat).setValue(
            "engine", "does-not-exist"
        )
        self.assertEqual(OverlaySettings(self.path).engine, ENGINE_WHISPER)

    def test_kind_round_trip_and_unknown_kind_falls_back(self) -> None:
        self.settings.kind = KIND_APPLICATION
        self.assertEqual(self.settings.kind, KIND_APPLICATION)
        QSettings(str(self.path), QSettings.Format.IniFormat).setValue(
            "source/kind", "speaker"
        )
        self.assertEqual(OverlaySettings(self.path).kind, KIND_MICROPHONE)

    def test_kind_rejects_unknown_values(self) -> None:
        with self.assertRaises(ValueError):
            self.settings.kind = "speaker"

    def test_microphone_round_trip_and_clearing(self) -> None:
        self.settings.microphone = 17
        self.assertEqual(self.settings.microphone, 17)
        self.settings.microphone = None
        self.assertIsNone(self.settings.microphone)

    def test_application_round_trip_and_clearing(self) -> None:
        self.settings.application = "douyin.exe"
        self.assertEqual(self.settings.application, "douyin.exe")
        self.settings.application = None
        self.assertIsNone(self.settings.application)

    def test_model_paths_are_only_returned_while_the_directory_exists(self) -> None:
        self.settings.whisper_model = self.path.parent
        self.assertEqual(self.settings.whisper_model, self.path.parent)
        missing = self.path.parent / "gone"
        self.settings.wav2vec_model = missing
        self.assertIsNone(self.settings.wav2vec_model)

    def test_values_survive_a_new_instance(self) -> None:
        self.settings.engine = ENGINE_WAV2VEC
        self.settings.kind = KIND_APPLICATION
        self.settings.microphone = 3
        reopened = OverlaySettings(self.path)
        self.assertEqual(reopened.engine, ENGINE_WAV2VEC)
        self.assertEqual(reopened.kind, KIND_APPLICATION)
        self.assertEqual(reopened.microphone, 3)


class ResolveModelTest(unittest.TestCase):
    def setUp(self) -> None:
        folder = Path(tempfile.gettempdir()) / f"liebad-models-{uuid.uuid4().hex}"
        folder.mkdir()
        self.addCleanup(lambda: __import__("shutil").rmtree(folder, True))
        self.folder = folder
        self.settings = OverlaySettings(folder / "overlay.ini")

    def test_whisper_model_precedence(self) -> None:
        explicit = self.folder / "explicit"
        remembered = self.folder / "remembered"
        from_env = self.folder / "from-env"
        remembered.mkdir()
        self.settings.whisper_model = remembered
        with environment(**{MODEL_ENV: str(from_env)}):
            self.assertEqual(
                resolve_whisper_model(explicit, self.settings), explicit
            )
            self.assertEqual(resolve_whisper_model(None, self.settings), from_env)
        self.assertEqual(resolve_whisper_model(None, self.settings), remembered)
        self.settings.whisper_model = None
        self.assertEqual(resolve_whisper_model(None, self.settings), DEFAULT_WHISPER_MODEL)

    def test_wav2vec_model_precedence(self) -> None:
        explicit = self.folder / "explicit"
        remembered = self.folder / "remembered"
        from_env = self.folder / "from-env"
        remembered.mkdir()
        self.settings.wav2vec_model = remembered
        with environment(**{WAV2VEC_MODEL_ENV: str(from_env)}):
            self.assertEqual(
                resolve_wav2vec_model(explicit, self.settings), explicit
            )
            self.assertEqual(resolve_wav2vec_model(None, self.settings), from_env)
        self.assertEqual(resolve_wav2vec_model(None, self.settings), remembered)
        self.settings.wav2vec_model = None
        self.assertEqual(
            resolve_wav2vec_model(None, self.settings), DEFAULT_WAV2VEC_DIR
        )


if __name__ == "__main__":
    unittest.main()
