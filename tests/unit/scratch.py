"""Scratch directories shared by the unit tests.

``tempfile.gettempdir()`` is not reliable in this workspace: the sandbox denies
writes into ``%TEMP%`` folders created with the default ``0o700`` mode, and it
can resolve to the repository root, which leaves untracked folders behind.
Tests keep throwaway files under the ignored ``temp/`` tree instead.
"""

from __future__ import annotations

import gc
import shutil
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "temp"


def scratch_dir(prefix: str) -> Path:
    """Create and return a unique directory under ``temp/``."""

    folder = ROOT / f"{prefix}-{uuid.uuid4().hex}"
    folder.mkdir(parents=True)
    return folder


def remove(folder: Path) -> None:
    """Delete a scratch directory, retrying while a handle is still open."""

    for _ in range(5):
        shutil.rmtree(folder, ignore_errors=True)
        if not folder.exists():
            return
        gc.collect()
        time.sleep(0.05)
