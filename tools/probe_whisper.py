"""Probe local faster-whisper transcription on Windows CPU (INT8).

Loads a CTranslate2 model from a local directory without touching the network,
transcribes one 16 kHz mono PCM WAV file and prints the timings used by
`docs/plan.md` task 1 and `docs/superpowers/plans/2026-11-23-liebad-implementation.md` task 1.

Usage:
    python tools/probe_whisper.py --model-dir models/faster-whisper-base --wav temp/audio/sample.wav
"""

from __future__ import annotations

import argparse
import sys
import time
import wave
from pathlib import Path
from typing import Callable

import numpy as np

EXPECTED_RATE = 16_000
EXPECTED_CHANNELS = 1
EXPECTED_WIDTH = 2  # 16-bit PCM


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Transcribe a local 16 kHz mono PCM WAV with faster-whisper (CPU INT8).",
    )
    parser.add_argument("--model-dir", required=True, type=Path, help="Local CTranslate2 model directory.")
    parser.add_argument("--wav", required=True, type=Path, help="16 kHz mono 16-bit PCM WAV file.")
    parser.add_argument("--language", default=None, help="Force a language code, e.g. zh. Default: auto-detect.")
    parser.add_argument("--gain", default=1.0, type=float, help="Multiply samples by this factor (clipped to [-1, 1]). Default: 1.0.")
    parser.add_argument("--prompt", default=None, help="Initial prompt passed to the decoder, e.g. a simplified-Chinese hint.")
    parser.add_argument("--keyword", default=None, help="Optional reference keyword to look for in the transcript.")
    parser.add_argument("--simplify", action="store_true", help="Convert the transcript from Traditional to Simplified Chinese (opencc t2s).")
    return parser.parse_args(argv)


def _make_simplifier() -> "Callable[[str], str]":
    """Return a Traditional-to-Simplified converter; importing lazily keeps the flag optional."""
    try:
        from opencc import OpenCC
    except ImportError as exc:
        raise SystemExit("error: --simplify needs opencc-python-reimplemented installed") from exc
    converter = OpenCC("t2s")
    return converter.convert


def load_wav(path: Path) -> tuple[np.ndarray, float, str]:
    """Validate the WAV contract and return (float32 mono samples, duration_seconds, description)."""
    if not path.is_file():
        raise SystemExit(f"error: wav not found: {path}")
    try:
        with wave.open(str(path), "rb") as handle:
            channels = handle.getnchannels()
            width = handle.getsampwidth()
            rate = handle.getframerate()
            frames = handle.getnframes()
            raw = handle.readframes(frames)
    except wave.Error as exc:
        raise SystemExit(f"error: not a PCM WAV file ({exc}): {path}") from exc
    if (rate, channels, width) != (EXPECTED_RATE, EXPECTED_CHANNELS, EXPECTED_WIDTH):
        raise SystemExit(
            "error: expected 16000 Hz mono 16-bit PCM, "
            f"got {rate} Hz, {channels} channel(s), {width * 8}-bit: {path}"
        )
    samples = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    duration = frames / float(rate) if rate else 0.0
    description = f"{rate} Hz, {channels} ch, {width * 8}-bit, {frames} frames, {duration:.3f} s"
    return samples, duration, description


def _print_versions() -> None:
    import ctranslate2
    import faster_whisper
    import onnxruntime

    print(f"faster-whisper: {faster_whisper.__version__}")
    print(f"ctranslate2:    {ctranslate2.__version__}")
    print(f"onnxruntime:    {onnxruntime.__version__}")


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    model_dir = args.model_dir
    if not model_dir.is_dir():
        raise SystemExit(f"error: model directory not found: {model_dir}")
    if not (model_dir / "model.bin").is_file() or not (model_dir / "tokenizer.json").is_file():
        raise SystemExit(f"error: model directory needs model.bin and tokenizer.json: {model_dir}")

    samples, duration, wav_description = load_wav(args.wav)
    peak = float(np.max(np.abs(samples))) if samples.size else 0.0
    if args.gain != 1.0:
        samples = np.clip(samples * args.gain, -1.0, 1.0)

    from faster_whisper import WhisperModel

    print(f"model_dir: {model_dir}")
    print(f"wav:       {args.wav}")
    print(f"format:    {wav_description}")
    print(f"gain:      {args.gain:g}  peak: {peak:.3f} -> {float(np.max(np.abs(samples))) if samples.size else 0.0:.3f}")
    _print_versions()

    load_started = time.perf_counter()
    model = WhisperModel(str(model_dir), device="cpu", compute_type="int8", local_files_only=True)
    load_seconds = time.perf_counter() - load_started

    transcribe_started = time.perf_counter()
    segments, info = model.transcribe(
        samples,
        language=args.language,
        beam_size=5,
        vad_filter=False,
        condition_on_previous_text=False,
        initial_prompt=args.prompt,
    )
    rows: list[tuple[float, float, str]] = []
    for segment in segments:
        rows.append((segment.start, segment.end, segment.text.strip()))
    inference_seconds = time.perf_counter() - transcribe_started

    simplify: Callable[[str], str] | None = _make_simplifier() if args.simplify else None
    if simplify is not None:
        rows = [(start, end, simplify(text)) for start, end, text in rows]

    print(f"device:    cpu  compute_type: int8  cpu_threads: auto")
    print(f"language:  {info.language}  probability: {info.language_probability:.3f}")
    print(f"load_s:    {load_seconds:.3f}")
    print(f"infer_s:   {inference_seconds:.3f}")
    print(f"audio_s:   {duration:.3f}")
    if duration > 0:
        print(f"rtf:       {inference_seconds / duration:.3f}  (infer_s / audio_s)")
    print(f"segments:  {len(rows)}")
    print(f"simplify:  {'opencc t2s' if simplify is not None else 'off'}")
    for start, end, text in rows:
        print(f"  {start:7.3f}-{end:7.3f}  {text}")

    transcript = "".join(text for _, _, text in rows).strip()
    print(f"transcript: {transcript}")
    if args.keyword is not None:
        compact = "".join(transcript.split())
        found = args.keyword in compact
        print(f"keyword:   {args.keyword!r} -> {'FOUND' if found else 'MISSING'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
