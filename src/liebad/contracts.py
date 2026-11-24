"""Types shared by the caption session, audio sources and speech recognizers."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterator, Protocol, Sequence

SAMPLE_RATE = 16_000
"""Sample rate the session, the sources and the recognizer agree on."""

FRAME_MS = 20
"""Frame length used for the RMS speech gate."""

FRAME_SAMPLES = SAMPLE_RATE * FRAME_MS // 1000


@dataclass(frozen=True)
class AudioBlock:
    """A slice of mono 16 kHz float audio at a session-relative sample offset."""

    samples: Sequence[float]
    start_sample: int


class AudioSource(Protocol):
    """Delivers audio blocks; after ``request_stop`` it drains and ends."""

    def blocks(self) -> Iterator[AudioBlock]:
        ...

    def request_stop(self) -> None:
        ...


class SpeechRecognizer(Protocol):
    """Turns a mono 16 kHz float window into text in the spoken language."""

    def recognize(self, mono16k: Sequence[float]) -> str:
        ...


@dataclass(frozen=True)
class FinalCaption:
    """One finalized caption segment."""

    segment_id: int
    text: str


class CaptionState(Enum):
    """Lifecycle of a caption session."""

    CAPTURING = "capturing"
    FINISHING = "finishing"
    COMPLETED = "completed"
    FAULTED = "faulted"


@dataclass(frozen=True)
class CaptionSnapshot:
    """Immutable view of the session published to the overlay."""

    state: CaptionState
    draft: str
    final: tuple[FinalCaption, ...]
    error: str | None = None


@dataclass(frozen=True)
class CaptionOptions:
    """Audio window parameters; every duration is in milliseconds."""

    partial_interval_ms: int = 500
    pause_duration_ms: int = 750
    max_segment_ms: int = 12_000
    speech_rms_threshold: float = 0.01
    min_speech_ms: int = 300
