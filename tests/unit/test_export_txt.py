"""Unit tests for the UTF-8 TXT export."""

from __future__ import annotations

import shutil
import tempfile
import unittest
import uuid
from pathlib import Path

from liebad.contracts import FinalCaption
from liebad.export_txt import write_txt


class ExportTxtTest(unittest.TestCase):
    def test_export_writes_utf8_in_final_order(self):
        captions = [FinalCaption(0, "第一句，中文。"), FinalCaption(1, "第二句，English 混说。")]
        # Default mkdir mode: the DSH sandbox cannot write inside 0700 temp dirs,
        # so TemporaryDirectory() is unusable here.
        folder = Path(tempfile.gettempdir()) / f"liebad-export-{uuid.uuid4().hex}"
        folder.mkdir()
        self.addCleanup(shutil.rmtree, folder, True)

        target = folder / "captions.txt"
        write_txt(target, captions)
        raw = target.read_bytes()

        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
        text = raw.decode("utf-8", errors="strict")
        self.assertEqual(text, "第一句，中文。\n第二句，English 混说。\n")
        self.assertEqual(text.splitlines(), [caption.text for caption in captions])


if __name__ == "__main__":
    unittest.main()
