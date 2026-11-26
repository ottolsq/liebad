"""Unit tests for the UTF-8 TXT export."""

from __future__ import annotations

import unittest

from liebad.contracts import FinalCaption
from liebad.export_txt import write_txt

try:  # discovery starts inside tests/unit, so the helper is importable directly
    from scratch import remove, scratch_dir
except ImportError:  # pragma: no cover - discovery from tests/
    from .scratch import remove, scratch_dir


class ExportTxtTest(unittest.TestCase):
    def test_export_writes_utf8_in_final_order(self):
        captions = [FinalCaption(0, "第一句，中文。"), FinalCaption(1, "第二句，English 混说。")]
        folder = scratch_dir("liebad-export")
        self.addCleanup(remove, folder)

        target = folder / "captions.txt"
        write_txt(target, captions)
        raw = target.read_bytes()

        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
        text = raw.decode("utf-8", errors="strict")
        self.assertEqual(text, "第一句，中文。\n第二句，English 混说。\n")
        self.assertEqual(text.splitlines(), [caption.text for caption in captions])


if __name__ == "__main__":
    unittest.main()
