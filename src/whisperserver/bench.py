"""Benchmark: transcribe one audio file with every downloaded model, one after another.

Runs as its own process so the live server keeps serving:
    python -m whisperserver.bench <audio> [--device GPU] [--runs 3] [--models repo1 repo2 ...]
Prints one JSON object per line: {"event": "start"|"loading"|"result"|"error"|"done", ...}
"""

from __future__ import annotations

import argparse
import dataclasses
import gc
import io
import json
import sys
import time
from pathlib import Path

from whisperserver.config import MODELS, data_dir, env_file_path, load_config, model_downloaded, read_env
from whisperserver.server import SR, Engine

REFERENCE_WAV = data_dir() / "reference.wav"


def emit(**event) -> None:
    print(json.dumps(event, ensure_ascii=False), flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="whisperserver.bench")
    parser.add_argument("audio", nargs="?", default=str(REFERENCE_WAV))
    parser.add_argument("--device")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--models", nargs="*")
    args = parser.parse_args(argv)
    if not Path(args.audio).is_file():
        parser.error(f"audio file not found: {args.audio} (record a reference in the settings or pass a file)")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    base = load_config(read_env(env_file_path()))
    device = (args.device or base.device).upper()
    from faster_whisper.audio import decode_audio

    data = Path(args.audio).read_bytes()
    audio_s = len(decode_audio(io.BytesIO(data), sampling_rate=SR)) / SR
    repos = args.models or [repo for repo, _ in MODELS]
    labels = dict(MODELS)
    todo = []
    for repo in repos:
        cfg = dataclasses.replace(base, model=repo, device=device, warnings=[])
        if model_downloaded(cfg.model_path):
            todo.append(cfg)
        else:
            emit(event="skipped", model=repo, label=labels.get(repo, repo), reason="not downloaded")
    emit(event="start", audio=str(args.audio), audio_s=round(audio_s, 2), device=device, models=len(todo))

    for cfg in todo:
        label = labels.get(cfg.model, cfg.model)
        emit(event="loading", model=cfg.model, label=label)
        engine = Engine(cfg)
        t0 = time.perf_counter()
        engine.load()
        load_s = time.perf_counter() - t0
        if engine.status != "ready":
            emit(event="error", model=cfg.model, label=label, error=engine.error)
            continue
        times, text = [], ""
        try:
            for _ in range(max(1, args.runs)):
                t1 = time.perf_counter()
                text, _ = engine.transcribe(data)
                times.append(time.perf_counter() - t1)
        except Exception as exc:  # noqa: BLE001
            emit(event="error", model=cfg.model, label=label, error=f"{type(exc).__name__}: {exc}")
            continue
        finally:
            engine.pipe = None
            del engine
            gc.collect()
        emit(event="result", model=cfg.model, label=label, load_s=round(load_s, 2), first_s=round(times[0], 2),
             best_s=round(min(times), 2), rtf=round(min(times) / audio_s, 3) if audio_s else None, text=text)
    emit(event="done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
