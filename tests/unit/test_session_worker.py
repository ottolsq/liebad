"""Engine dispatch tests for SessionWorker (no models are loaded)."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from liebad.ui.session_worker import SessionWorker  # noqa: E402


def make_worker(engine: str, **kwargs) -> SessionWorker:
    return SessionWorker(
        lambda: None, Path("models/faster-whisper-small"), engine=engine, **kwargs
    )


class EngineDispatchTest(unittest.TestCase):
    def test_whisper_keeps_the_injected_pair(self) -> None:
        final = SimpleNamespace(name="final")
        partial = SimpleNamespace(name="partial")
        worker = make_worker("whisper", recognizer=final, partial_recognizer=partial)
        self.assertEqual(worker._build_recognizers(), (final, partial))

    def test_wav2vec_uses_the_injected_recognizer_for_both_roles(self) -> None:
        final = SimpleNamespace(name="ctc")
        worker = make_worker("wav2vec", recognizer=final)
        self.assertEqual(worker._build_recognizers(), (final, None))

    def test_hybrid_keeps_whisper_finals_and_injected_ctc_drafts(self) -> None:
        final = SimpleNamespace(name="final")
        partial = SimpleNamespace(name="ctc")
        worker = make_worker("hybrid", recognizer=final, partial_recognizer=partial)
        self.assertEqual(worker._build_recognizers(), (final, partial))

    def test_wav2vec_reports_model_phases_before_loading_and_warmup(self) -> None:
        for engine, final in (("wav2vec", None), ("hybrid", object())):
            with self.subTest(engine=engine):
                worker = make_worker(engine, recognizer=final)
                events = []
                worker.model_status.connect(events.append)

                def load(_directory, **_kwargs):
                    events.append("load")
                    return SimpleNamespace(warm_up=lambda: events.append("warm"))

                modules = {"liebad.wav2vec_recognizer": SimpleNamespace(Wav2VecRecognizer=load)}
                with (
                    patch.dict(sys.modules, modules),
                    patch("liebad.ui.session_worker.require_model_dir", side_effect=lambda path: path),
                ):
                    worker._build_recognizers()

                self.assertEqual(
                    events,
                    ["正在加载模型：wav2vec 2.0", "load", "正在预热模型：wav2vec 2.0", "warm"],
                )

    def test_unknown_engine_is_rejected_before_any_loading(self) -> None:
        with self.assertRaises(ValueError):
            make_worker("vosk")

    def test_building_recognizers_does_not_open_the_source(self) -> None:
        opened = []
        worker = SessionWorker(
            lambda: opened.append(True),
            Path("models/faster-whisper-small"),
            engine="whisper",
            recognizer=SimpleNamespace(),
            partial_recognizer=None,
        )
        worker._build_recognizers()
        self.assertEqual(opened, [])


if __name__ == "__main__":
    unittest.main()
