"""Regression tests for model loading in the caption overlay."""

import io
import os
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import patch

from PySide6.QtWidgets import QApplication

from liebad.ui.overlay import CaptionOverlay
from liebad.ui.settings import OverlaySettings
try:
    from scratch import remove, scratch_dir
except ImportError:  # discovery from tests/
    from .scratch import remove, scratch_dir


class OverlayTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with patch.dict(os.environ, {"QT_QPA_PLATFORM": "offscreen"}):
            cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.folder = scratch_dir("overlay")
        self.addCleanup(remove, self.folder)
        with patch("liebad.ui.overlay.list_microphones", return_value=[]):
            self.overlay = CaptionOverlay(settings=OverlaySettings(self.folder / "overlay.ini"))
        self.addCleanup(self.overlay.close)
        self.overlay.show()
        self.app.processEvents()

    def test_startup_reports_each_phase_before_doing_the_work(self):
        overlay = self.overlay
        overlay._model_dir = self.folder / "whisper-final"
        partial_dir = self.folder / "whisper-draft"
        terminal = io.StringIO()
        phases = []

        def observe(message):
            self.assertIn(message, overlay._status.toolTip())
            self.assertIn(message, terminal.getvalue().splitlines()[-1])
            self.assertFalse(overlay._start.isEnabled())
            phases.append(message)

        def load(directory, **_kwargs):
            observe(f"正在加载模型：{directory.name}")
            return SimpleNamespace(warm_up=lambda: observe(f"正在预热模型：{directory.name}"))

        with (
            redirect_stdout(terminal),
            patch("liebad.ui.overlay.partial_model_dir", return_value=partial_dir),
            patch("liebad.ui.overlay.WhisperRecognizer", side_effect=load),
        ):
            overlay._load_models()

        self.assertEqual(len(phases), 4)
        self.assertIn("就绪", overlay._status.text())
        self.assertIn("就绪", terminal.getvalue().splitlines()[-1])
        self.assertTrue(overlay._start.isEnabled())

    def test_startup_reports_warmup_failure(self):
        terminal = io.StringIO()

        def fail():
            raise RuntimeError("test warm-up error")

        with (
            redirect_stdout(terminal),
            patch("liebad.ui.overlay.partial_model_dir", return_value=None),
            patch(
                "liebad.ui.overlay.WhisperRecognizer",
                return_value=SimpleNamespace(warm_up=fail),
            ),
        ):
            self.overlay._load_models()

        self.assertIn("预热模型失败", self.overlay._status.toolTip())
        self.assertIn("test warm-up error", terminal.getvalue())
        self.assertFalse(self.overlay._start.isEnabled())
