"""Run the Liebad caption prototype."""

from __future__ import annotations

import signal
import sys

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QApplication

from liebad.ui import CaptionOverlay


def main(argv: list[str] | None = None) -> int:
    interrupted = False

    def request_close(_signum, _frame) -> None:
        nonlocal interrupted
        interrupted = True

    previous_handler = signal.signal(signal.SIGINT, request_close)
    try:
        app = QApplication(sys.argv if argv is None else argv)
        overlay = CaptionOverlay()
        overlay._prepare_model_loading()
        # The tool window is the app's only main window.
        overlay.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose)
        overlay.show()

        def load_models() -> None:
            if not interrupted:
                overlay._load_models()

        def close_if_interrupted() -> None:
            if interrupted:
                overlay.close()

        # Let Python receive SIGINT while Qt is idle, and close the window
        # between Qt callbacks instead of interrupting one with an exception.
        interrupt_timer = QTimer()
        interrupt_timer.timeout.connect(close_if_interrupted)
        interrupt_timer.start(100)
        QTimer.singleShot(100, load_models)
        return app.exec()
    finally:
        signal.signal(signal.SIGINT, previous_handler)


if __name__ == "__main__":
    raise SystemExit(main())
