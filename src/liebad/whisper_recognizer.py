"""Local Whisper recognizer built on faster-whisper and CTranslate2."""

from __future__ import annotations

import os
from collections.abc import Sequence
from pathlib import Path

import numpy as np
from faster_whisper import WhisperModel
from opencc import OpenCC

from .contracts import SAMPLE_RATE

#: Environment variable the application reads the local model directory from.
MODEL_ENV = "LIEBAD_WHISPER_MODEL"

#: Optional environment override for the decoding language.
LANGUAGE_ENV = "LIEBAD_WHISPER_LANGUAGE"

#: Files a CTranslate2 Whisper directory must provide before we load it.
REQUIRED_FILES = ("model.bin", "tokenizer.json")


def model_dir_from_env() -> Path:
    """Return the configured model directory, or explain what is missing."""

    raw = os.environ.get(MODEL_ENV)
    if not raw:
        raise RuntimeError(f"{MODEL_ENV} is not set")
    path = Path(raw).expanduser()
    missing = [name for name in REQUIRED_FILES if not (path / name).is_file()]
    if not path.is_dir() or missing:
        detail = f"missing {', '.join(missing)}" if missing else "not a directory"
        raise FileNotFoundError(f"invalid Whisper model directory {path}: {detail}")
    return path


class WhisperRecognizer:
    """Recognize 16 kHz mono audio with a local CTranslate2 Whisper model.

    The model is loaded once and reused for every window, matching the CPU
    INT8 configuration validated in the test records (``language="zh"``,
    ``beam_size=5``, no VAD). Text is converted to Simplified Chinese with
    OpenCC after decoding, because the model itself picks glyphs per audio.
    """

    def __init__(
        self,
        model_dir: Path | str,
        *,
        language: str | None = None,
        beam_size: int = 5,
        simplify: bool = True,
    ) -> None:
        self._model_dir = Path(model_dir).expanduser()
        missing = [name for name in REQUIRED_FILES if not (self._model_dir / name).is_file()]
        if not self._model_dir.is_dir() or missing:
            detail = f"missing {', '.join(missing)}" if missing else "not a directory"
            raise FileNotFoundError(
                f"invalid Whisper model directory {self._model_dir}: {detail}"
            )
        self._language = language or os.environ.get(LANGUAGE_ENV) or "zh"
        self._beam_size = beam_size
        self._simplifier = OpenCC("t2s").convert if simplify else None
        self._model = WhisperModel(
            str(self._model_dir),
            device="cpu",
            compute_type="int8",
            local_files_only=True,
        )

    @classmethod
    def from_env(cls) -> "WhisperRecognizer":
        """Build a recognizer from ``LIEBAD_WHISPER_MODEL``."""

        return cls(model_dir_from_env())

    @property
    def model_dir(self) -> Path:
        return self._model_dir

    @property
    def language(self) -> str:
        return self._language

    def recognize(self, mono16k: Sequence[float]) -> str:
        """Decode one window and return the complete transcript text."""

        if len(mono16k) == 0:
            return ""
        audio = np.asarray(mono16k, dtype=np.float32)
        segments, _info = self._model.transcribe(
            audio,
            language=self._language,
            task="transcribe",
            beam_size=self._beam_size,
            vad_filter=False,
            condition_on_previous_text=False,
        )
        text = "".join(segment.text for segment in segments)
        if self._simplifier is not None:
            text = self._simplifier(text)
        return text.strip()


__all__ = [
    "LANGUAGE_ENV",
    "MODEL_ENV",
    "REQUIRED_FILES",
    "WhisperRecognizer",
    "model_dir_from_env",
    "SAMPLE_RATE",
]
