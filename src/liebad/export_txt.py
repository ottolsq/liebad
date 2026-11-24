"""Write finalized captions to a UTF-8 text file, one caption per line."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from .contracts import FinalCaption


def write_txt(path: Path, captions: Sequence[FinalCaption]) -> None:
    """Write ``captions`` in order as strict UTF-8, one line per segment."""

    text = "".join(f"{caption.text}\n" for caption in captions)
    Path(path).write_text(text, encoding="utf-8", newline="\n")
