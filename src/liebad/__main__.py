"""Run the Liebad caption prototype."""

from __future__ import annotations

import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from liebad.ui import CaptionOverlay


def main(argv: list[str] | None = None) -> int:
    app = QApplication(sys.argv if argv is None else argv)
    overlay = CaptionOverlay()
    overlay.show()
    QTimer.singleShot(100, overlay._load_models)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
