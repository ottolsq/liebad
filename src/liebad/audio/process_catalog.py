"""List applications with visible windows so their audio can be captured."""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

_EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


@dataclass(frozen=True)
class AppSource:
    """A capture target: one process and the window that represents it."""

    pid: int
    process_name: str
    window_title: str

    @property
    def label(self) -> str:
        if self.window_title:
            return f"{self.process_name} · {self.window_title}"
        return self.process_name


def _user32():
    return ctypes.WinDLL("user32", use_last_error=True)


def _kernel32():
    return ctypes.WinDLL("kernel32", use_last_error=True)


def _visible_window_titles() -> list[tuple[int, str]]:
    """Visible top-level windows with a non-empty title, as (pid, title)."""
    user32 = _user32()
    rows: list[tuple[int, str]] = []

    def collect(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        title = buffer.value.strip()
        if not title:
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value:
            rows.append((int(pid.value), title))
        return True

    callback = _EnumWindowsProc(collect)
    user32.EnumWindows(callback, 0)
    return rows


def _process_name(pid: int) -> str:
    """Executable name of ``pid`` or a placeholder when it cannot be opened."""
    kernel32 = _kernel32()
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return f"pid {pid}"
    try:
        size = wintypes.DWORD(32768)
        buffer = ctypes.create_unicode_buffer(size.value)
        if kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return Path(buffer.value).name
        return f"pid {pid}"
    finally:
        kernel32.CloseHandle(handle)


def _build_sources(
    rows: Iterable[tuple[int, str]],
    name_of: Callable[[int], str],
    *,
    exclude_pid: int | None,
) -> list[AppSource]:
    """Collapse windows to one entry per process, keeping the longest title."""
    by_pid: dict[int, AppSource] = {}
    for pid, title in rows:
        if pid == exclude_pid or not title:
            continue
        current = by_pid.get(pid)
        if current is None or len(title) > len(current.window_title):
            by_pid[pid] = AppSource(pid, name_of(pid), title)
    return sorted(
        by_pid.values(),
        key=lambda source: (source.process_name.lower(), source.window_title.lower(), source.pid),
    )


def list_app_sources(*, exclude_pid: int | None = None) -> list[AppSource]:
    """Applications that currently own a visible window."""
    excluded = os.getpid() if exclude_pid is None else exclude_pid
    return _build_sources(_visible_window_titles(), _process_name, exclude_pid=excluded)
