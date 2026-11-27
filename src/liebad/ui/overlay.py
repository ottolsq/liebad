"""Top-most caption overlay: pick a microphone, start, stop and export."""

from __future__ import annotations

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
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from liebad.audio import (
    MicrophoneSource,
    ProcessLoopbackSource,
    list_app_sources,
    list_microphones,
)
from liebad.contracts import (
    SAMPLE_RATE,
    CaptionOptions,
    CaptionSnapshot,
    CaptionState,
    FinalCaption,
)
from liebad.engines import (
    ENGINE_HYBRID,
    ENGINE_LABELS,
    ENGINE_WAV2VEC,
    ENGINE_WHISPER,
    normalize_engine,
)
from liebad.export_txt import write_txt
from liebad.ui.session_worker import SessionWorker, partial_model_dir
from liebad.ui.settings import (
    KIND_APPLICATION,
    OverlaySettings,
    resolve_wav2vec_model,
    resolve_whisper_model,
)
from liebad.whisper_recognizer import WhisperRecognizer

DEFAULT_MODEL_DIR = Path("models/faster-whisper-small")
MODEL_ENV = "LIEBAD_WHISPER_MODEL"
WINDOW_HEIGHT = 150
APP_GAIN = 1.0
SOURCE_KINDS = (("mic", "麦克风"), ("app", "应用（进程回环）"))
ENGINE_CHOICES = (
    (ENGINE_WHISPER, "Whisper（定稿准）"),
    (ENGINE_WAV2VEC, "wav2vec 2.0（首字快）"),
    (ENGINE_HYBRID, "混合（wav2vec 草稿 + Whisper 定稿）"),
)


class _PreviewLabel(QLabel):
    """Show one line without letting long text resize the window."""

    def __init__(self, elide: Qt.TextElideMode, prefix: str = "") -> None:
        super().__init__()
        self._elide = elide
        self._prefix = prefix
        self._full_text = ""
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)

    def setText(self, text: str) -> None:  # noqa: N802 - Qt override
        self._full_text = text
        self.setToolTip(text)
        self._render_text()

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        self._render_text()

    def _render_text(self) -> None:
        if not self._full_text:
            super().setText("")
            return
        line = " ".join(self._full_text.splitlines())
        metrics = self.fontMetrics()
        width = max(0, self.contentsRect().width() - metrics.horizontalAdvance(self._prefix))
        super().setText(self._prefix + metrics.elidedText(line, self._elide, width))


class CaptionOverlay(QWidget):
    """Always-on-top caption bar with microphone selection and TXT export."""

    def __init__(
        self,
        model_dir: Path | None = None,
        parent: QWidget | None = None,
        preload: bool = False,
        settings: OverlaySettings | None = None,
        wav2vec_dir: Path | None = None,
    ) -> None:
        super().__init__(parent)
        self._settings = settings or OverlaySettings()
        self._model_dir = resolve_whisper_model(model_dir, self._settings)
        self._wav2vec_dir = resolve_wav2vec_model(wav2vec_dir, self._settings)
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

        self._kind = QComboBox()
        for value, text in SOURCE_KINDS:
            self._kind.addItem(text, value)
        self._kind.setMinimumWidth(150)
        self._device = QComboBox()
        self._device.setMinimumWidth(300)
        self._engine = QComboBox()
        for value, text in ENGINE_CHOICES:
            self._engine.addItem(text, value)
        self._engine.setMinimumWidth(170)
        self._engine.setCurrentIndex(
            max(0, self._engine.findData(self._settings.engine))
        )
        self._kind.setCurrentIndex(max(0, self._kind.findData(self._settings.kind)))
        self._refresh = QPushButton("刷新")
        self._start = QPushButton("开始")
        self._stop = QPushButton("停止")
        self._export = QPushButton("导出")
        self._stop.setEnabled(False)
        self._export.setEnabled(False)

        row = QHBoxLayout()
        row.addWidget(QLabel("音源"))
        row.addWidget(self._kind)
        row.addWidget(self._device, 1)
        row.addWidget(self._refresh)
        row.addWidget(QLabel("识别"))
        row.addWidget(self._engine)
        row.addWidget(self._start)
        row.addWidget(self._stop)
        row.addWidget(self._export)

        self._status = _PreviewLabel(Qt.TextElideMode.ElideRight)
        self._status.setText("就绪")
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
        self._refresh.clicked.connect(self._refresh_sources)
        self._kind.currentIndexChanged.connect(self._refresh_sources)
        self._refresh_sources()
        self._move_to_top()
        if preload:
            self._load_models()

    # ----------------------------------------------------------------- models

    def _prepare_model_loading(self) -> None:
        self._start.setEnabled(False)
        self._status.setText("等待加载模型…")

    def _load_models(self) -> None:
        """Load both models up front so pressing "开始" starts capture at once."""

        self._start.setEnabled(False)
        self._show_model_status(f"正在加载模型：{self._model_dir.name}")
        try:
            final = WhisperRecognizer(self._model_dir, cpu_threads=6)
            partial_dir = partial_model_dir(self._model_dir)
            partial = None
            if partial_dir is not None:
                self._show_model_status(f"正在加载模型：{partial_dir.name}")
                partial = WhisperRecognizer(partial_dir, beam_size=1, cpu_threads=2)
        except Exception as exc:
            self._show_model_status(f"加载模型失败：{type(exc).__name__}: {exc}")
            return
        try:
            self._show_model_status(f"正在预热模型：{self._model_dir.name}")
            final.warm_up()
            if partial_dir is not None and partial is not None:
                self._show_model_status(f"正在预热模型：{partial_dir.name}")
                partial.warm_up()
        except Exception as exc:
            self._show_model_status(f"预热模型失败：{type(exc).__name__}: {exc}")
            return
        self._recognizer = final
        self._partial_recognizer = partial
        names = self._model_dir.name
        if partial_dir is not None:
            names += f" + {partial_dir.name}"
        extra = "，wav2vec 2.0 可选" if self._wav2vec_dir.is_dir() else ""
        self._start.setEnabled(True)
        self._show_model_status(
            f"就绪，模型已加载（{names}{extra}），{self._device.count()} 个输入设备"
        )

    def _show_model_status(self, message: str) -> None:
        print(f"[Liebad] {message}", flush=True)
        self._status.setText(message)
        self._status.repaint()

    # ---------------------------------------------------------------- devices

    def _kind_value(self) -> str:
        return str(self._kind.currentData() or "mic")

    def _engine_value(self) -> str:
        return normalize_engine(self._engine.currentData())

    def _refresh_sources(self) -> None:
        kind = self._kind_value()
        self._device.clear()
        if kind == "app":
            try:
                sources = list_app_sources()
            except Exception as exc:
                self._status.setText(f"无法枚举应用：{exc}")
                return
            for source in sources:
                self._device.addItem(source.label, source.pid)
                self._device.setItemData(
                    self._device.count() - 1,
                    source.process_name,
                    Qt.ItemDataRole.UserRole + 1,
                )
            self._restore_device(kind)
            if not sources:
                self._status.setText("没有找到正在播放的应用窗口")
            else:
                self._status.setText(f"就绪，{len(sources)} 个应用窗口")
            return
        try:
            devices = list_microphones()
        except Exception as exc:
            self._status.setText(f"无法枚举麦克风：{exc}")
            return
        for index, name in devices:
            self._device.addItem(f"{index} · {name}", index)
        self._restore_device(kind)
        if not devices:
            self._status.setText("没有找到 WASAPI 输入设备")
        else:
            self._status.setText(f"就绪，{len(devices)} 个输入设备")

    def _restore_device(self, kind: str) -> None:
        """Reselect the device or application remembered from the last run."""

        if kind == KIND_APPLICATION:
            remembered = self._settings.application
            if not remembered:
                return
            for index in range(self._device.count()):
                process_name = self._device.itemData(
                    index, Qt.ItemDataRole.UserRole + 1
                )
                if process_name == remembered:
                    self._device.setCurrentIndex(index)
                    return
            return
        remembered_device = self._settings.microphone
        if remembered_device is None:
            return
        index = self._device.findData(remembered_device)
        if index >= 0:
            self._device.setCurrentIndex(index)

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
        source_id = self._device.currentData()
        kind = self._kind_value()
        engine = self._engine_value()
        if source_id is None:
            self._status.setText(
                "请先选择一个应用窗口" if kind == "app" else "请先选择一个输入设备"
            )
            return
        if engine in (ENGINE_WAV2VEC, ENGINE_HYBRID) and not self._wav2vec_dir.is_dir():
            self._status.setText(f"wav2vec 2.0 模型目录不存在：{self._wav2vec_dir}")
            return
        if engine in (ENGINE_WHISPER, ENGINE_HYBRID) and self._recognizer is None:
            self._status.setText("模型还在加载，请稍候再点开始")
            return
        if not self._model_dir.is_dir():
            self._status.setText(f"模型目录不存在：{self._model_dir}")
            return
        self._captions = ()
        self._first_text_at = None
        self._draft.setText("")
        self._final.setText("")
        self._remember_choice(kind, engine, source_id)

        if kind == "app":
            pid = int(source_id)
            label = self._device.currentText()

            def open_source():
                return ProcessLoopbackSource(pid, gain=APP_GAIN)
        else:
            device = int(source_id)
            label = self._device.currentText()

            def open_source():
                return MicrophoneSource(device)

        worker = SessionWorker(
            open_source,
            self._model_dir,
            CaptionOptions(
                partial_interval_ms=400,
                pause_duration_ms=1200,
                speech_rms_threshold=0.02,
            ),
            recognizer=(
                self._recognizer
                if engine in (ENGINE_WHISPER, ENGINE_HYBRID)
                else None
            ),
            partial_recognizer=(
                self._partial_recognizer if engine == ENGINE_WHISPER else None
            ),
            engine=engine,
            wav2vec_dir=self._wav2vec_dir,
        )
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.snapshot_ready.connect(self._on_snapshot)
        worker.capture_started.connect(self._on_capture_started)
        worker.finished.connect(self._on_finished)
        worker.failed.connect(self._on_failed)
        self._worker = worker
        self._thread = thread
        self._started_at = time.perf_counter()
        self._set_running(True)
        self._status.setText(
            f"采集中（{label} · {ENGINE_LABELS[engine]}）…"
        )
        thread.start()

    def stop_capture(self) -> None:
        if self._worker is not None:
            self._worker.request_stop()
            self._status.setText("收尾中…")
            self._stop.setEnabled(False)

    def _remember_choice(self, kind: str, engine: str, source_id: object) -> None:
        """Persist the choices so the next launch starts where this one did."""

        self._settings.engine = engine
        self._settings.kind = kind
        if kind == KIND_APPLICATION:
            process_name = self._device.itemData(
                self._device.currentIndex(), Qt.ItemDataRole.UserRole + 1
            )
            if process_name:
                self._settings.application = str(process_name)
        else:
            self._settings.microphone = int(source_id)  # type: ignore[arg-type]
        self._settings.whisper_model = self._model_dir
        self._settings.wav2vec_model = self._wav2vec_dir

    def _set_running(self, running: bool) -> None:
        self._kind.setEnabled(not running)
        self._refresh.setEnabled(not running)
        self._device.setEnabled(not running)
        self._engine.setEnabled(not running)
        self._start.setEnabled(not running)
        self._stop.setEnabled(running)
        self._export.setEnabled(False if running else bool(self._captions))

    def _on_capture_started(self) -> None:
        # Models may load inside the worker; measure the first-text delay from
        # the moment audio actually starts flowing, not from the button click.
        self._started_at = time.perf_counter()
        self._first_text_at = None
        self._status.setText("采集中…说话即可看到临时字幕")

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
            self._handle_fault(snapshot.error)
        elif snapshot.state is CaptionState.FINISHING:
            self._status.setText("收尾中…")
        elif snapshot.state is CaptionState.CAPTURING:
            self._status.setText("采集中…说话即可看到临时字幕")

    def _handle_fault(self, message: str) -> None:
        if "exited" in message:
            detail = "目标应用已退出，请重新选择音源后再开始"
        else:
            detail = message
        self._set_running(False)
        if self._kind_value() == "app":
            self._refresh_sources()
        self._status.setText(f"错误：{detail}")

    def _on_finished(self, snapshot: CaptionSnapshot) -> None:
        self._on_snapshot(snapshot)
        self._captions = snapshot.final
        self._teardown_thread()
        self._set_running(False)
        if snapshot.state is CaptionState.FAULTED and snapshot.error:
            self._handle_fault(snapshot.error)
        elif self._first_text_at is not None and self._started_at is not None:
            delay = self._first_text_at - self._started_at
            self._status.setText(f"已完成，{len(self._captions)} 段，首字 {delay:.1f} s，可导出")
        elif self._captions:
            self._status.setText(f"已完成，{len(self._captions)} 段，可导出")
        else:
            self._status.setText("已完成，没有识别到文字")

    def _on_failed(self, message: str) -> None:
        self._teardown_thread()
        self._handle_fault(message)

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
        self._settings.sync()
        super().closeEvent(event)
