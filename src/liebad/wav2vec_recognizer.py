"""Chinese wav2vec 2.0 CTC recognizer."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Sequence

import numpy as np

MODEL_ENV = "LIEBAD_WAV2VEC_MODEL"
REQUIRED_FILES = ("config.json", "preprocessor_config.json", "vocab.json")


class Wav2VecRecognizer:
    """CTC recognizer backed by a Chinese fine-tuned wav2vec 2.0 checkpoint."""

    def __init__(self, model_dir: Path | str, *, torch_threads: int = 6, simplify: bool = True) -> None:
        self._model_dir = Path(model_dir)
        if not self._model_dir.is_dir():
            raise FileNotFoundError(f"{self._model_dir} is not a directory")
        missing = [name for name in REQUIRED_FILES if not (self._model_dir / name).is_file()]
        if missing:
            raise FileNotFoundError(f"{self._model_dir} is missing {', '.join(missing)}")

        import torch
        from transformers import AutoModelForCTC, AutoProcessor

        torch.set_num_threads(max(1, torch_threads))
        self._torch = torch
        self._processor = AutoProcessor.from_pretrained(str(self._model_dir))
        self._model = AutoModelForCTC.from_pretrained(str(self._model_dir)).eval()
        self._simplify = simplify
        self._lock = threading.Lock()
        self._converter = None

    @property
    def model_dir(self) -> Path:
        return self._model_dir

    def warm_up(self) -> None:
        self.recognize(np.zeros(8_000, dtype=np.float32))

    def recognize(self, mono16k: Sequence[float]) -> str:
        audio = np.asarray(mono16k, dtype=np.float32)
        if audio.size == 0:
            return ""
        with self._lock:
            inputs = self._processor(audio, sampling_rate=16_000, return_tensors="pt")
            with self._torch.inference_mode():
                logits = self._model(inputs.input_values).logits
            ids = self._torch.argmax(logits, dim=-1)
            text = self._processor.batch_decode(ids)[0]
        text = " ".join(text.split())
        if self._simplify and text:
            text = self._simplifier().convert(text)
        return text.strip()

    def _simplifier(self):
        if self._converter is None:
            from opencc import OpenCC

            self._converter = OpenCC("t2s")
        return self._converter


def model_dir_from_env() -> Path:
    import os

    value = os.environ.get(MODEL_ENV)
    if not value:
        raise RuntimeError(f"{MODEL_ENV} is not set")
    return Path(value)


__all__ = ["MODEL_ENV", "Wav2VecRecognizer", "model_dir_from_env"]
