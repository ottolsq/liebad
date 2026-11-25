"""Background caption session used by the Qt overlay."""

from __future__ import annotations

import os
import threading
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

from liebad.contracts import AudioSource, CaptionOptions, CaptionSnapshot
from liebad.engines import (
    ENGINE_WAV2VEC,
    ENGINE_WHISPER,
    normalize_engine,
    require_model_dir,
    wav2vec_model_dir,
)
from liebad.session import CaptionSession
from liebad.whisper_recognizer import WhisperRecognizer

#: Optional smaller model used for provisional text; finals keep the main model.
PARTIAL_MODEL_ENV = "LIEBAD_WHISPER_PARTIAL_MODEL"

#: Sibling directory tried when the environment variable is absent.
DEFAULT_PARTIAL_DIR = "faster-whisper-base"


def partial_model_dir(model_dir: Path | str) -> Path | None:
    """Return the provisional model directory, if one is configured or present."""

    raw = os.environ.get(PARTIAL_MODEL_ENV)
    if raw:
        return Path(raw).expanduser()
    candidate = Path(model_dir).expanduser().parent / DEFAULT_PARTIAL_DIR
    return candidate if candidate.is_dir() else None


class SessionWorker(QObject):
    """Run one caption session on a worker thread and republish its snapshots."""

    snapshot_ready = Signal(object)
    finished = Signal(object)
    failed = Signal(str)
    capture_started = Signal()

    def __init__(
        self,
        source_factory: Callable[[], AudioSource],
        model_dir: Path,
        options: CaptionOptions | None = None,
        parent: QObject | None = None,
        recognizer=None,
        partial_recognizer=None,
        engine: str = ENGINE_WHISPER,
        wav2vec_dir: Path | None = None,
    ) -> None:
        super().__init__(parent)
        self._source_factory = source_factory
        self._model_dir = Path(model_dir)
        self._options = options
        self._recognizer = recognizer
        self._partial_recognizer = partial_recognizer
        self._engine = normalize_engine(engine)
        self._wav2vec_dir = wav2vec_dir
        self._lock = threading.Lock()
        self._session: CaptionSession | None = None
        self._stop_requested = False

    @Slot()
    def run(self) -> None:
        snapshot: CaptionSnapshot | None = None
        try:
            recognizer, partial = self._build_recognizers()
            with self._lock:
                stop_requested = self._stop_requested
            # Open the microphone only after the models are ready, so the input
            # queue never holds audio recorded before recognition could start.
            source = self._source_factory()
            self.capture_started.emit()
            session = CaptionSession(
                source,
                recognizer,
                self._publish,
                self._options,
                partial_recognizer=partial,
            )
            with self._lock:
                self._session = session
                stop_requested = self._stop_requested
            if stop_requested:
                session.request_stop()
            snapshot = session.run()
        except Exception as exc:
            with self._lock:
                self._session = None
            self.failed.emit(f"{type(exc).__name__}: {exc}")
            return
        with self._lock:
            self._session = None
        self.finished.emit(snapshot)

    def _build_recognizers(self):
        """Return the final and provisional recognizers for the chosen engine."""

        if self._recognizer is not None:
            return self._recognizer, self._partial_recognizer
        if self._engine == ENGINE_WAV2VEC:
            return self._make_wav2vec()
        recognizer = WhisperRecognizer(self._model_dir, cpu_threads=6)
        return recognizer, self._partial_recognizer or self._load_partial_recognizer()

    def _make_wav2vec(self):
        """Load the CTC engine; it serves finals and drafts with one instance."""

        from liebad.wav2vec_recognizer import Wav2VecRecognizer

        directory = require_model_dir(wav2vec_model_dir(self._wav2vec_dir))
        model = Wav2VecRecognizer(directory, torch_threads=6)
        # The first forward pass pays framework and allocator warm-up; do it
        # before the source opens so the first draft is not delayed by it.
        model.warm_up()
        return model, None

    def _load_partial_recognizer(self) -> WhisperRecognizer | None:
        """Load the cheaper provisional model, or fall back to the main one."""

        partial_dir = partial_model_dir(self._model_dir)
        if partial_dir is None or partial_dir == self._model_dir:
            return None
        try:
            return WhisperRecognizer(partial_dir, beam_size=1, cpu_threads=2)
        except (FileNotFoundError, OSError, RuntimeError):
            return None

    def request_stop(self) -> None:
        with self._lock:
            self._stop_requested = True
            session = self._session
        if session is not None:
            session.request_stop()

    def _publish(self, snapshot: CaptionSnapshot) -> None:
        self.snapshot_ready.emit(snapshot)
