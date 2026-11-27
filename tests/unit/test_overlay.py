"""Regression tests for overlay placement, caption preview and TXT export."""

import io
import os
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import patch

from PySide6.QtCore import Qt, qInstallMessageHandler
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton

from liebad.contracts import CaptionSnapshot, CaptionState, FinalCaption
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
        self.startup_messages = []
        previous_handler = qInstallMessageHandler(
            lambda _mode, _context, message: self.startup_messages.append(message)
        )
        try:
            with patch("liebad.ui.overlay.list_microphones", return_value=[]):
                self.overlay = CaptionOverlay(settings=OverlaySettings(self.folder / "overlay.ini"))
        finally:
            qInstallMessageHandler(previous_handler)
        self.addCleanup(self.overlay.close)
        self.overlay.show()
        self.app.processEvents()

    def test_window_is_narrower_than_work_area_and_inset_from_top(self):
        overlay = self.overlay
        work_area = overlay.screen().availableGeometry()
        self.assertLess(overlay.frameGeometry().width(), work_area.width())
        self.assertGreater(overlay.frameGeometry().top(), work_area.top())
        self.assertTrue(work_area.contains(overlay.frameGeometry()))

    def test_close_button_is_aligned_with_controls_and_closes_overlay(self):
        button = self.overlay.findChild(QPushButton, "closeButton")
        self.assertIsNotNone(button)
        self.assertEqual(button.geometry().right(), self.overlay._refresh.geometry().right())
        self.assertLess(button.geometry().bottom(), self.overlay._refresh.geometry().top())
        QTest.mouseClick(button, Qt.MouseButton.LeftButton)
        self.assertFalse(self.overlay.isVisible())

    def test_tab_after_export_focuses_close_button(self):
        self.assertFalse(any("QWidget::setTabOrder" in msg for msg in self.startup_messages))
        button = self.overlay.findChild(QPushButton, "closeButton")
        export = self.overlay._export
        export.setEnabled(True)
        export.setFocus()
        self.assertIs(self.overlay.focusWidget(), export)
        QTest.keyClick(export, Qt.Key.Key_Tab)
        self.assertIs(self.overlay.focusWidget(), button)

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

    def test_close_button_turns_red_only_on_hover(self):
        button = self.overlay.findChild(QPushButton, "closeButton")
        window = self.overlay.windowHandle()

        def background_color():
            image = button.grab().toImage()
            offset = round(6 * image.devicePixelRatio())
            return image.pixelColor(offset, offset)

        QTest.mouseClick(self.overlay._status, Qt.MouseButton.LeftButton)
        content = self.overlay._status.geometry().center()
        QTest.mouseMove(window, content)
        idle = background_color()
        QTest.mouseMove(window, button.geometry().center())
        hovered = background_color()
        self.assertGreater(hovered.red(), max(hovered.green(), hovered.blue()) + 80)
        self.assertNotEqual(hovered, idle)
        QTest.mouseMove(window, content)
        self.assertEqual(background_color(), idle)

    def test_long_caption_preview_retains_tail_and_export_retains_full_text(self):
        draft = "一段很长的草稿 mixed text " * 40 + "最新草稿"
        finals = (FinalCaption(1, "一段很长的定稿 " * 60 + "最新定稿"),)
        width = self.overlay.width()
        self.overlay._on_snapshot(CaptionSnapshot(CaptionState.COMPLETED, draft, finals))
        self.app.processEvents()
        self.assertEqual(self.overlay.width(), width)
        self.assertTrue(self.overlay._draft.text().startswith("…"))
        self.assertTrue(self.overlay._draft.text().endswith("最新草稿"))
        self.assertTrue(self.overlay._final.text().startswith("定稿：…"))
        self.assertTrue(self.overlay._final.text().endswith("最新定稿"))
        path = self.folder / "字幕.txt"
        self.overlay.export_to(path)
        self.assertEqual(path.read_text(encoding="utf-8"), finals[0].text + "\n")

    def test_final_preview_marks_older_segments_as_hidden(self):
        finals = tuple(FinalCaption(i, str(i)) for i in range(5))
        self.overlay._on_snapshot(CaptionSnapshot(CaptionState.COMPLETED, "", finals))
        self.assertEqual(self.overlay._final.text(), "定稿：… 2 / 3 / 4")
