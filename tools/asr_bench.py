"""Compare Whisper and wav2vec 2.0 on the same replayed clips."""

from __future__ import annotations

import argparse
import csv
import difflib
import re
import sys
import time
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Sequence

from liebad.contracts import CaptionOptions
from liebad.replay_audio import ReplayAudioSource
from liebad.session import CaptionSession

PUNCTUATION = re.compile(r"[\W_]+", re.UNICODE)
CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")


@dataclass(frozen=True)
class Sample:
    audio: Path
    reference: str
    language: str
    speech_start: float


@dataclass
class RunResult:
    sample: str
    engine: str
    language: str
    final: str = ""
    first_draft: str = ""
    first_char_s: float | None = None
    revisions: int = 0
    drafts: int = 0
    errors: int = 0
    units: int = 0
    seconds: float = 0.0
    events: list[tuple[float, str]] = field(default_factory=list)

    @property
    def cer(self) -> float:
        return self.errors / self.units if self.units else 0.0


def normalize(text: str) -> str:
    folded = unicodedata.normalize("NFKC", text).lower()
    return PUNCTUATION.sub("", folded)


def units(text: str) -> list[str]:
    """Chinese characters count one each, runs of Latin letters count as words."""
    result: list[str] = []
    buffer = ""
    for char in normalize(text):
        if CJK.match(char):
            if buffer:
                result.append(buffer)
                buffer = ""
            result.append(char)
        else:
            buffer += char
    if buffer:
        result.append(buffer)
    return result


def edit_distance(reference: Sequence[str], hypothesis: Sequence[str]) -> int:
    previous = list(range(len(hypothesis) + 1))
    for i, ref_unit in enumerate(reference, start=1):
        current = [i]
        for j, hyp_unit in enumerate(hypothesis, start=1):
            cost = 0 if ref_unit == hyp_unit else 1
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + cost))
        previous = current
    return previous[-1]


def score(reference: str, hypothesis: str) -> tuple[int, int]:
    ref_units = units(reference)
    hyp_units = units(hypothesis)
    return edit_distance(ref_units, hyp_units), len(ref_units)


def load_manifest(path: Path) -> list[Sample]:
    samples: list[Sample] = []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            samples.append(
                Sample(
                    audio=Path(row["audio"]),
                    reference=row["reference"],
                    language=(row.get("language") or "zh").strip(),
                    speech_start=float(row["speechStartSeconds"]),
                )
            )
    return samples


def run_sample(
    sample: Sample,
    engine: str,
    make_recognizer: Callable[[], object],
    *,
    options: CaptionOptions,
    target_peak: float,
) -> RunResult:
    result = RunResult(sample=sample.audio.name, engine=engine, language=sample.language)
    recognizer = make_recognizer()
    probe = ReplayAudioSource(sample.audio)
    peak = max((abs(value) for value in probe.read_samples()), default=0.0)
    gain = target_peak / peak if peak > 0 and target_peak > 0 else 1.0
    started = time.monotonic()
    drafts: list[str] = []

    def publish(snapshot) -> None:
        now = time.monotonic() - started
        text = snapshot.draft.strip()
        result.events.append((round(now, 3), text))
        if text and not result.first_draft:
            result.first_draft = text
            result.first_char_s = round(now - sample.speech_start, 2)
        if text and (not drafts or drafts[-1] != text):
            drafts.append(text)
        if snapshot.final:
            result.final = " ".join(caption.text for caption in snapshot.final).strip()

    source = ReplayAudioSource(sample.audio, gain=gain)
    session = CaptionSession(source, recognizer, publish, options=options)
    snapshot = session.run()
    result.seconds = round(time.monotonic() - started, 2)
    result.final = " ".join(snapshot.final and [c.text for c in snapshot.final] or []).strip() or result.final
    result.drafts = len(drafts)
    result.revisions = max(0, len(drafts) - 1)
    result.errors, result.units = score(sample.reference, result.final)
    return result


def write_results(path: Path, runs: Sequence[RunResult]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            ["sample", "engine", "language", "final", "first_draft", "first_char_s", "drafts", "revisions", "errors", "units", "cer", "seconds"]
        )
        for run in runs:
            writer.writerow(
                [
                    run.sample,
                    run.engine,
                    run.language,
                    run.final,
                    run.first_draft,
                    "" if run.first_char_s is None else run.first_char_s,
                    run.drafts,
                    run.revisions,
                    run.errors,
                    run.units,
                    f"{run.cer:.3f}",
                    run.seconds,
                ]
            )


def print_table(runs: Sequence[RunResult]) -> None:
    header = f"{'sample':24s} {'engine':8s} {'first':>6s} {'rev':>4s} {'err':>7s} {'cer':>6s} {'sec':>6s}"
    print(header)
    print("-" * len(header))
    for run in runs:
        first = "-" if run.first_char_s is None else f"{run.first_char_s:.2f}"
        print(
            f"{run.sample[:24]:24s} {run.engine:8s} {first:>6s} {run.revisions:4d} "
            f"{run.errors:3d}/{run.units:<3d} {run.cer:6.3f} {run.seconds:6.2f}"
        )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--whisper-model", type=Path, required=True)
    parser.add_argument("--wav2vec-model", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--engine", choices=("both", "whisper", "wav2vec"), default="both")
    parser.add_argument("--gain", type=float, default=0.3, help="peak the clip is normalised to")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args(argv)

    samples = load_manifest(args.manifest)
    if args.limit:
        samples = samples[: args.limit]

    engines: list[tuple[str, Callable[[], object]]] = []
    if args.engine in ("both", "whisper"):
        from liebad.whisper_recognizer import WhisperRecognizer

        engines.append(("whisper", lambda: WhisperRecognizer(args.whisper_model, cpu_threads=6)))
    if args.engine in ("both", "wav2vec"):
        from liebad.wav2vec_recognizer import Wav2VecRecognizer

        engines.append(("wav2vec", lambda: Wav2VecRecognizer(args.wav2vec_model, torch_threads=6)))

    options = CaptionOptions(partial_interval_ms=400, pause_duration_ms=1200, speech_rms_threshold=0.02)
    runs: list[RunResult] = []
    for engine, factory in engines:
        for sample in samples:
            print(f"running {engine} on {sample.audio.name} ...", flush=True)
            runs.append(run_sample(sample, engine, factory, options=options, target_peak=args.gain))
    print_table(runs)
    write_results(args.out, runs)
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
