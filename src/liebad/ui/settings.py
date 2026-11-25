"""Remember the overlay's last engine, source and model directories."""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QSettings

from ..engines import (
    DEFAULT_WAV2VEC_DIR,
    ENGINE_WHISPER,
    WAV2VEC_MODEL_ENV,
    normalize_engine,
)

KIND_MICROPHONE = "mic"
KIND_APPLICATION = "app"
SOURCE_KINDS = (KIND_MICROPHONE, KIND_APPLICATION)

MODEL_ENV = "LIEBAD_WHISPER_MODEL"
SETTINGS_ENV = "LIEBAD_SETTINGS"
DEFAULT_WHISPER_MODEL = Path("models/faster-whisper-small")

_FALLBACK_FILE = ".liebad-settings.ini"

_ENGINE_KEY = "engine"
_KIND_KEY = "source/kind"
_MICROPHONE_KEY = "source/microphone"
_APPLICATION_KEY = "source/application"
_WHISPER_KEY = "model/whisper"
_WAV2VEC_KEY = "model/wav2vec"


class OverlaySettings:
    """Typed facade over ``QSettings`` for the overlay's last choices.

    The file lives under ``%APPDATA%`` normally, ``LIEBAD_SETTINGS`` when that
    variable is set, and next to the working directory when neither is
    writable (sandboxes deny ``%APPDATA%`` writes).
    """

    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path is not None else _writable_settings_path()
        self._settings = QSettings(str(self.path), QSettings.Format.IniFormat)

    # ---------------------------------------------------------------- engine

    @property
    def engine(self) -> str:
        """Last engine name, falling back to Whisper for blank or unknown values."""

        try:
            return normalize_engine(self._settings.value(_ENGINE_KEY, ""))
        except ValueError:
            return ENGINE_WHISPER

    @engine.setter
    def engine(self, value: str) -> None:
        self._settings.setValue(_ENGINE_KEY, normalize_engine(value))

    # ------------------------------------------------------------------ kind

    @property
    def kind(self) -> str:
        value = self._text(_KIND_KEY)
        return value if value in SOURCE_KINDS else KIND_MICROPHONE

    @kind.setter
    def kind(self, value: str) -> None:
        if value not in SOURCE_KINDS:
            raise ValueError(f"unknown source kind: {value!r}")
        self._settings.setValue(_KIND_KEY, value)

    # --------------------------------------------------------------- sources

    @property
    def microphone(self) -> int | None:
        """Device index of the last microphone, if one was remembered."""

        value = self._text(_MICROPHONE_KEY)
        if value is None:
            return None
        try:
            return int(value)
        except ValueError:
            return None

    @microphone.setter
    def microphone(self, value: int | None) -> None:
        if value is None:
            self._settings.remove(_MICROPHONE_KEY)
        else:
            self._settings.setValue(_MICROPHONE_KEY, str(int(value)))

    @property
    def application(self) -> str | None:
        """Process name of the last captured application, if one was remembered."""

        return self._text(_APPLICATION_KEY)

    @application.setter
    def application(self, value: str | None) -> None:
        if value is None:
            self._settings.remove(_APPLICATION_KEY)
        else:
            self._settings.setValue(_APPLICATION_KEY, value)

    # ---------------------------------------------------------------- models

    @property
    def whisper_model(self) -> Path | None:
        return self._directory(_WHISPER_KEY)

    @whisper_model.setter
    def whisper_model(self, value: Path | None) -> None:
        self._store_directory(_WHISPER_KEY, value)

    @property
    def wav2vec_model(self) -> Path | None:
        return self._directory(_WAV2VEC_KEY)

    @wav2vec_model.setter
    def wav2vec_model(self, value: Path | None) -> None:
        self._store_directory(_WAV2VEC_KEY, value)

    # --------------------------------------------------------------- helpers

    def sync(self) -> None:
        """Flush pending writes; ``QSettings`` otherwise holds them in memory."""

        self._settings.sync()

    def _text(self, key: str) -> str | None:
        value = self._settings.value(key, "")
        text = str(value).strip() if value is not None else ""
        return text or None

    def _directory(self, key: str) -> Path | None:
        text = self._text(key)
        if text is None:
            return None
        path = Path(text)
        return path if path.is_dir() else None

    def _store_directory(self, key: str, value: Path | None) -> None:
        if value is None:
            self._settings.remove(key)
        else:
            self._settings.setValue(key, str(value))


def _candidate_paths() -> list[Path]:
    override = os.environ.get(SETTINGS_ENV, "").strip()
    if override:
        return [Path(override)]
    paths: list[Path] = []
    appdata = os.environ.get("APPDATA", "").strip()
    if appdata:
        paths.append(Path(appdata) / "Liebad" / "overlay.ini")
    paths.append(Path.cwd() / _FALLBACK_FILE)
    return paths


def _can_write(path: Path) -> bool:
    probe = path.parent / f".liebad-probe-{os.getpid()}"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        probe.write_text("", encoding="utf-8")
        probe.unlink()
    except OSError:
        return False
    return True


def _writable_settings_path() -> Path:
    candidates = _candidate_paths()
    for candidate in candidates:
        if _can_write(candidate):
            return candidate
    return candidates[-1]


def _environment_path(name: str) -> Path | None:
    value = os.environ.get(name, "").strip()
    return Path(value) if value else None


def resolve_whisper_model(
    explicit: Path | str | None = None,
    settings: OverlaySettings | None = None,
) -> Path:
    """Pick the Whisper model directory: argument, env var, last choice, default."""

    if explicit is not None:
        return Path(explicit)
    from_env = _environment_path(MODEL_ENV)
    if from_env is not None:
        return from_env
    remembered = settings.whisper_model if settings is not None else None
    return remembered if remembered is not None else DEFAULT_WHISPER_MODEL


def resolve_wav2vec_model(
    explicit: Path | str | None = None,
    settings: OverlaySettings | None = None,
) -> Path:
    """Pick the wav2vec 2.0 directory: argument, env var, last choice, default."""

    if explicit is not None:
        return Path(explicit)
    from_env = _environment_path(WAV2VEC_MODEL_ENV)
    if from_env is not None:
        return from_env
    remembered = settings.wav2vec_model if settings is not None else None
    return remembered if remembered is not None else Path(DEFAULT_WAV2VEC_DIR)
