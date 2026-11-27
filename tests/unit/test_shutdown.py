"""Regression test for closing the launched caption window."""

import os
import subprocess
import sys
import textwrap
import unittest

try:
    from scratch import remove, scratch_dir
except ImportError:  # discovery from tests/
    from .scratch import remove, scratch_dir


class ShutdownTest(unittest.TestCase):
    def test_closing_overlay_exits_the_application(self):
        self._assert_clean_exit("close")

    def test_ctrl_c_exits_during_model_warmup(self):
        self._assert_clean_exit("warmup")

    def test_ctrl_c_exits_while_idle(self):
        self._assert_clean_exit("idle")

    def _assert_clean_exit(self, action):
        # A separate process exercises QApplication.exec() and Python exit.
        # Keep the real window and close event, without models or devices.
        folder = scratch_dir("shutdown")
        self.addCleanup(remove, folder)
        probe = textwrap.dedent('''
            import _thread
            import sys
            import threading
            from unittest.mock import patch

            from PySide6.QtCore import QTimer
            from PySide6.QtWidgets import QApplication
            from liebad import __main__ as entry
            from liebad.ui import CaptionOverlay

            action = sys.argv[1]

            class ClosingOverlay(CaptionOverlay):
                def __init__(self):
                    super().__init__()
                    if action == "close":
                        QTimer.singleShot(150, self.close)
                    QTimer.singleShot(5000, lambda: QApplication.instance().exit(5))

                def _load_models(self):
                    if action == "warmup":
                        _thread.interrupt_main()
                    elif action == "idle":
                        interrupt = threading.Timer(0.25, _thread.interrupt_main)
                        interrupt.start()

                def closeEvent(self, event):
                    super().closeEvent(event)
                    print("Window closed:", event.isAccepted(), flush=True)

            with (
                patch.object(entry, "CaptionOverlay", ClosingOverlay),
                patch("liebad.ui.overlay.list_microphones", return_value=[]),
                patch("liebad.ui.overlay.list_app_sources", return_value=[]),
            ):
                raise SystemExit(entry.main([]))
        ''')
        result = subprocess.run(
            [sys.executable, "-c", probe, action],
            env={
                **os.environ,
                "QT_QPA_PLATFORM": "offscreen",
                "LIEBAD_SETTINGS": str(folder / "overlay.ini"),
            },
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Window closed: True", result.stdout)
        self.assertNotIn("KeyboardInterrupt", result.stderr)
