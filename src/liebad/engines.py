"""Recognition engines the overlay can run, and where their weights live."""

from __future__ import annotations

import os
from pathlib import Path

ENGINE_WHISPER = "whisper"
ENGINE_WAV2VEC = "wav2vec"
ENGINE_HYBRID = "hybrid"

#: Engines offered in the UI, in display order.
ENGINES = (ENGINE_WHISPER, ENGINE_WAV2VEC, ENGINE_HYBRID)

#: Short names used in status lines.
ENGINE_LABELS = {
    ENGINE_WHISPER: "Whisper",
    ENGINE_WAV2VEC: "wav2vec",
    ENGINE_HYBRID: "混合",
}

#: Environment override for the wav2vec 2.0 checkpoint directory.
WAV2VEC_MODEL_ENV = "LIEBAD_WAV2VEC_MODEL"

#: Checkpoint bundled under ``models/`` for the wav2vec 2.0 engine.
DEFAULT_WAV2VEC_DIR = Path("models/wav2vec2-large-xlsr-53-chinese-zh-cn")


def normalize_engine(value: str | None) -> str:
    """Map a user-supplied engine name onto a supported engine."""

    text = (value or "").strip().lower()
    if not text:
        return ENGINE_WHISPER
    if text in ENGINES:
        return text
    raise ValueError(f"unknown engine: {value!r}")


def wav2vec_model_dir(explicit: Path | str | None = None) -> Path:
    """Return the checkpoint directory: argument first, then env, then default."""

    if explicit is not None:
        return Path(explicit).expanduser()
    raw = os.environ.get(WAV2VEC_MODEL_ENV)
    if raw:
        return Path(raw).expanduser()
    return DEFAULT_WAV2VEC_DIR


def require_model_dir(path: Path) -> Path:
    """Return ``path`` if it is a directory, otherwise raise FileNotFoundError."""

    if not path.is_dir():
        raise FileNotFoundError(f"model directory not found: {path}")
    return path
