"""Top-most caption overlay: pick a microphone, start, stop and export."""

from __future__ import annotations

import os
import time
from pathlib import Path

from PySide6.QtCore import Qt, QThread
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from liebad.audio import MicrophoneSource, list_microphones
from liebad.contracts import (
    SAMPLE_RATE,
    CaptionOptions,
    CaptionSnapshot,
    CaptionState,
    FinalCaption,
)
from liebad.export_txt import write_txt
from liebad.ui.session_worker import SessionWorker, partial_model_dir
from liebad.whisper_recognizer import WhisperRecognizer

DEFAULT_MODEL_DIR = Path("models/faster-whisper-small")
MODEL_ENV = "LIEBAD_WHISPER_MODEL"
WINDOW_HEIGHT = 150


class CaptionOverlay(QWidget):
    """Always-on-top caption bar with microphone selection and TXT export."""

    def __init__(
        self,
        model_dir: Path | None = None,
        parent: QWidget | None = None,
        preload: bool = False,
    ) -> None:
        super().__init__(parent)
        self._model_dir = Path(
            model_dir or os.environ.get(MODEL_ENV) or DEFAULT_MODEL_DIR
        )
        self._thread: QThread | None = None
        self._worker: SessionWorker | None = None
        self._recognizer: WhisperRecognizer | None = None
        self._partial_recognizer: WhisperRecognizer | None = None
        self._captions: tuple[FinalCaption, ...] = ()
        self._started_at: float | None = None
        self._first_text_at: float | None = None

        self.setWindowTitle("Liebad 字幕")
        self.setWindowFlags(
            Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool
        )
        self.setMinimumHeight(WINDOW_HEIGHT)

        self._device = QComboBox()
        self._device.setMinimumWidth(260)
        self._start = QPushButton("开始")
        self._stop = QPushButton("停止")
        self._export = QPushButton("导出")
        self._stop.setEnabled(False)
        self._export.setEnabled(False)

        row = QHBoxLayout()
        row.addWidget(QLabel("麦克风"))
        row.addWidget(self._device, 1)
        row.addWidget(self._start)
        row.addWidget(self._stop)
        row.addWidget(self._export)

        self._status = QLabel("就绪")
        self._draft = QLabel("")
        draft_font = QFont()
        draft_font.setPointSize(18)
        draft_font.setBold(True)
        self._draft.setFont(draft_font)
        self._draft.setWordWrap(True)
        self._draft.setMinimumHeight(52)
        self._draft.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self._final = QLabel("")
        self._final.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.addLayout(row)
        layout.addWidget(self._status)
        layout.addWidget(self._draft)
        layout.addWidget(self._final)

        self._start.clicked.connect(self.start_capture)
        self._stop.clicked.connect(self.stop_capture)
        self._export.clicked.connect(self._choose_export)
        self._refresh_devices()
        self._move_to_top()
        if preload:
            self._load_models()

    # ----------------------------------------------------------------- models

    def _load_models(self) -> None:
        """Load both models up front so pressing "开始" starts capture at once."""

        try:
            self._recognizer = WhisperRecognizer(self._model_dir, cpu_threads=6)
            partial_dir = partial_model_dir(self._model_dir)
            self._partial_recognizer = (
                WhisperRecognizer(partial_dir, beam_size=1, cpu_threads=2)
                if partial_dir is not None
                else None
            )
        except Exception as exc:
            self._status.setText(f"加载模型失败：{type(exc).__name__}: {exc}")
            self._start.setEnabled(False)
            return
        # The first inference of a fresh CTranslate2 model costs several
        # seconds of warm-up; pay it here instead of on the first draft.
        for recognizer in (self._recognizer, self._partial_recognizer):
            if recognizer is not None:
                recognizer.warm_up()
        names = self._model_dir.name
        if self._partial_recognizer is not None:
            names += f" + {Path(partial_model_dir(self._model_dir) or '').name}"
        self._status.setText(f"就绪，模型已加载（{names}），{self._device.count()} 个输入设备")

    # ---------------------------------------------------------------- devices

    def _refresh_devices(self) -> None:
        try:
            devices = list_microphones()
        except Exception as exc:
            self._status.setText(f"无法枚举麦克风：{exc}")
            return
        self._device.clear()
        for index, name in devices:
            self._device.addItem(f"{index} · {name}", index)
        if not devices:
            self._status.setText("没有找到 WASAPI 输入设备")
        else:
            self._status.setText(f"就绪，{len(devices)} 个输入设备")

    def _move_to_top(self) -> None:
        screen = self.screen() or QApplication.primaryScreen()
        if screen is None:
            return
        area = screen.availableGeometry()
        self.setGeometry(area.x(), area.y(), area.width(), WINDOW_HEIGHT)

    # ------------------------------------------------------------------ run

    def start_capture(self) -> None:
        if self._thread is not None:
            return
        device = self._device.currentData()
        if device is None:
            self._status.setText("请先选择一个输入设备")
            return
        if self._recognizer is None:
            self._status.setText("模型还在加载，请稍候再点开始")
            return
        if not self._model_dir.is_dir():
            self._status.setText(f"模型目录不存在：{self._model_dir}")
            return
        self._captions = ()
        self._first_text_at = None
        self._draft.setText("")
        self._final.setText("")

        def open_source():
            return MicrophoneSource(int(device))

        worker = SessionWorker(
            open_source,
            self._model_dir,
            CaptionOptions(
                partial_interval_ms=400,
                pause_duration_ms=1200,
                speech_rms_threshold=0.02,
            ),
            recognizer=self._recognizer,
            partial_recognizer=self._partial_recognizer,
        )
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.snapshot_ready.connect(self._on_snapshot)
        worker.finished.connect(self._on_finished)
        worker.failed.connect(self._on_failed)
        self._worker = worker
        self._thread = thread
        self._started_at = time.perf_counter()
        self._set_running(True)
        self._status.setText("采集中…说话即可看到临时字幕")
        thread.start()

    def stop_capture(self) -> None:
        if self._worker is not None:
            self._worker.request_stop()
            self._status.setText("收尾中…")
            self._stop.setEnabled(False)

    def _set_running(self, running: bool) -> None:
        self._device.setEnabled(not running)
        self._start.setEnabled(not running)
        self._stop.setEnabled(running)
        self._export.setEnabled(False if running else bool(self._captions))

    def _on_snapshot(self, snapshot: CaptionSnapshot) -> None:
        if snapshot.draft and self._first_text_at is None:
            self._first_text_at = time.perf_counter()
        self._draft.setText(snapshot.draft)
        self._captions = snapshot.final
        if snapshot.final:
            self._final.setText(
                "定稿：" + " / ".join(caption.text for caption in snapshot.final[-3:])
            )
        if snapshot.state is CaptionState.FAULTED and snapshot.error:
            self._status.setText(f"错误：{snapshot.error}")
        elif snapshot.state is CaptionState.FINISHING:
            self._status.setText("收尾中…")
        elif snapshot.state is CaptionState.CAPTURING:
            self._status.setText("采集中…说话即可看到临时字幕")

    def _on_finished(self, snapshot: CaptionSnapshot) -> None:
        self._on_snapshot(snapshot)
        self._captions = snapshot.final
        self._teardown_thread()
        self._set_running(False)
        if self._first_text_at is not None and self._started_at is not None:
            delay = self._first_text_at - self._started_at
            self._status.setText(f"已完成，{len(self._captions)} 段，首字 {delay:.1f} s，可导出")
        elif self._captions:
            self._status.setText(f"已完成，{len(self._captions)} 段，可导出")
        else:
            self._status.setText("已完成，没有识别到文字")

    def _on_failed(self, message: str) -> None:
        self._teardown_thread()
        self._set_running(False)
        self._status.setText(f"错误：{message}")

    def _teardown_thread(self, grace_ms: int = 20_000) -> None:
        thread = self._thread
        self._thread = None
        self._worker = None
        if thread is not None:
            thread.quit()
            thread.wait(grace_ms)

    # --------------------------------------------------------------- export

    def _choose_export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "导出字幕", "captions.txt", "文本文件 (*.txt)"
        )
        if path:
            self.export_to(Path(path))

    def export_to(self, path: Path) -> None:
        if not self._captions:
            self._status.setText("还没有定稿可导出")
            return
        write_txt(path, self._captions)
        self._status.setText(f"已导出 {len(self._captions)} 段到 {path}")

    # ---------------------------------------------------------------- window

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt override
        if self._worker is not None:
            self._worker.request_stop()
        self._teardown_thread()
        super().closeEvent(event)
