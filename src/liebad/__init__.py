"""Liebad: local real-time Chinese captions on Windows."""

from __future__ import annotations

from .contracts import (
    FRAME_MS,
    FRAME_SAMPLES,
    SAMPLE_RATE,
    AudioBlock,
    AudioSource,
    CaptionOptions,
    CaptionSnapshot,
    CaptionState,
    FinalCaption,
    SpeechRecognizer,
)
from .export_txt import write_txt
from .session import CaptionSession

__version__ = "0.1.0"

__all__ = [
    "FRAME_MS",
    "FRAME_SAMPLES",
    "SAMPLE_RATE",
    "AudioBlock",
    "AudioSource",
    "CaptionOptions",
    "CaptionSession",
    "CaptionSnapshot",
    "CaptionState",
    "FinalCaption",
    "SpeechRecognizer",
    "write_txt",
]
