"""The HTTP server process (started and supervised by the tray watchdog).

OpenAI-compatible:  POST /v1/audio/transcriptions  (multipart: file, language, prompt, response_format)
Watchdog probe:     GET  /health            -> {"status": "downloading" | "loading" | "ready" | "error", ...}
                    GET  /health?deep=1     -> additionally runs a tiny inference (detects a hung GPU)

Run directly for debugging:  python -m whisperserver.server
"""

from __future__ import annotations

import io
import logging
import logging.handlers
import os
import sys
import threading
import time

from whisperserver.config import Config, ensure_models_dir, env_file_path, load_config, model_downloaded, read_env

try:  # module level: FastAPI resolves the (string) annotations of the endpoints in this namespace
    from fastapi import UploadFile
except ImportError:  # pragma: no cover
    UploadFile = None
SR = 16000
# Whole-text outputs Whisper is known to invent for (near-)silent German audio.
HALLUCINATIONS = {
    "vielen dank.", "vielen dank fürs zuschauen.", "vielen dank für's zuschauen!", "danke.",
    "untertitel im auftrag des zdf, 2017", "untertitel im auftrag des zdf, 2018", "untertitel im auftrag des zdf, 2020",
    "untertitel der amara.org-community", "untertitelung aufgrund der amara.org-community",
    "copyright wdr 2021", "swr 2020", "tschüss.", "bis zum nächsten mal.",
}

log = logging.getLogger("whisperserver.server")


class Engine:
    """Owns the OpenVINO pipeline; loads it in the background so /health answers immediately."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.status = "loading"
        self.error = ""
        self.pipe = None
        self.gen_cfg = None
        self.lock = threading.Lock()
        self.started = time.time()
        self.requests = 0

    def load(self) -> None:
        try:
            path = self.cfg.model_path
            if not model_downloaded(path):
                self.status = "downloading"
                log.info("Model not found in %s, downloading %s", path, self.cfg.model)
                ensure_models_dir(self.cfg.models_dir)
                try:
                    import truststore
                    truststore.inject_into_ssl()
                except ImportError:
                    pass
                from huggingface_hub import snapshot_download
                snapshot_download(self.cfg.model, local_dir=str(path))
            self.status = "loading"
            import numpy as np
            import openvino_genai as ov_genai

            t0 = time.perf_counter()
            # Compiled-kernel cache: later loads (reboot, wake, model switch) skip the GPU compilation.
            cache_dir = self.cfg.models_dir / ".ovcache"
            cache_dir.mkdir(parents=True, exist_ok=True)
            pipe = ov_genai.WhisperPipeline(str(path), self.cfg.device, CACHE_DIR=str(cache_dir))
            gen_cfg = pipe.get_generation_config()
            gen_cfg.language = f"<|{self.cfg.language}|>"
            gen_cfg.task = "transcribe"
            gen_cfg.return_timestamps = False
            pipe.generate(np.zeros(SR, dtype=np.float32).tolist(), gen_cfg)  # compile kernels now
            self.pipe, self.gen_cfg = pipe, gen_cfg
            self.status = "ready"
            log.info("Model %s on %s ready in %.1f s", path.name, self.cfg.device, time.perf_counter() - t0)
        except Exception as exc:  # noqa: BLE001 - reported via /health, the watchdog restarts us
            self.status, self.error = "error", f"{type(exc).__name__}: {exc}"
            log.exception("Loading the model failed")

    def strip_silence(self, audio):
        import numpy as np
        if not self.cfg.vad:
            return audio
        from faster_whisper.vad import VadOptions, collect_chunks, get_speech_timestamps
        chunks = get_speech_timestamps(audio, VadOptions(min_silence_duration_ms=500, speech_pad_ms=300))
        if not chunks:
            return np.zeros(0, dtype=np.float32)
        return np.concatenate(collect_chunks(audio, chunks)[0])

    def generate(self, audio, prompt: str | None = None) -> str:
        with self.lock:
            use_prompt = bool(prompt) and hasattr(self.gen_cfg, "initial_prompt")
            if use_prompt:
                self.gen_cfg.initial_prompt = prompt
            try:
                return str(self.pipe.generate(audio.tolist(), self.gen_cfg)).strip()
            finally:
                if use_prompt:
                    self.gen_cfg.initial_prompt = None

    def transcribe(self, data: bytes, prompt: str | None = None) -> tuple[str, float]:
        from faster_whisper.audio import decode_audio
        audio = decode_audio(io.BytesIO(data), sampling_rate=SR)
        duration = len(audio) / SR
        speech = self.strip_silence(audio)
        if len(speech) < SR // 4:
            return "", duration
        text = self.generate(speech, prompt)
        if text.lower() in HALLUCINATIONS:
            log.info("Dropped likely hallucination: %r", text)
            text = ""
        self.requests += 1
        return text, duration

    def deep_check(self) -> float:
        import numpy as np
        t0 = time.perf_counter()
        rng = np.random.default_rng(0)
        self.generate((rng.standard_normal(SR) * 0.001).astype(np.float32))
        return time.perf_counter() - t0


def create_app(engine: Engine):
    from fastapi import FastAPI, File, Form, HTTPException
    from fastapi.concurrency import run_in_threadpool
    from fastapi.responses import PlainTextResponse

    app = FastAPI(title="Local German Whisper", version="1")
    cfg = engine.cfg

    @app.get("/health")
    def health(deep: int = 0):
        body = {"status": engine.status, "model": cfg.model_path.name, "device": cfg.device,
                "language": cfg.language, "pid": os.getpid(), "uptime_s": round(time.time() - engine.started),
                "requests": engine.requests}
        if engine.error:
            body["error"] = engine.error
        if deep and engine.status == "ready":
            body["deep_s"] = round(engine.deep_check(), 3)
        return body

    @app.get("/v1/models")
    @app.get("/openai/v1/models")
    def models():
        return {"object": "list", "data": [{"id": "whisper-large-v3-turbo", "object": "model", "owned_by": "local"}]}

    @app.post("/v1/audio/transcriptions")
    @app.post("/openai/v1/audio/transcriptions")  # Groq-style path
    async def transcriptions(file: UploadFile = File(...), model: str = Form(""),
                             language: str = Form(""), prompt: str | None = Form(None),
                             response_format: str = Form("json"), temperature: float = Form(0.0)):
        if engine.status != "ready":
            raise HTTPException(503, f"model not ready ({engine.status})")
        if language and language.lower()[:2] != cfg.language:
            log.debug("Requested language %s ignored, server is fixed to %s", language, cfg.language)
        data = await file.read()
        if not data:
            raise HTTPException(400, "empty file")
        t0 = time.perf_counter()
        try:
            text, duration = await run_in_threadpool(engine.transcribe, data, prompt)
        except Exception as exc:  # noqa: BLE001 - e.g. undecodable audio
            log.warning("Transcription of %s failed: %s", file.filename, exc)
            raise HTTPException(400, f"transcription failed: {exc}") from exc
        log.info("%s: %.1f s audio in %.2f s, %d chars", file.filename, duration, time.perf_counter() - t0,
                 len(text))
        if response_format in ("text", "srt", "vtt"):
            return PlainTextResponse(text)
        if response_format == "verbose_json":
            segment = {"id": 0, "seek": 0, "start": 0.0, "end": duration, "text": text, "tokens": [],
                       "temperature": 0.0, "avg_logprob": 0.0, "compression_ratio": 1.0, "no_speech_prob": 0.0}
            return {"task": "transcribe", "language": "german", "duration": duration, "text": text,
                    "segments": [segment] if text else [], "words": []}
        return {"text": text}

    return app


def setup_logging(cfg: Config) -> None:
    cfg.log_dir.mkdir(parents=True, exist_ok=True)
    log_file = cfg.log_dir / "server.log"
    if sys.stderr is None:  # pythonw: keep stray prints/tracebacks
        sys.stdout = sys.stderr = open(log_file.with_suffix(".stderr.log"), "a", encoding="utf-8", buffering=1)
    handler = logging.handlers.RotatingFileHandler(log_file, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(cfg.log_level)


def main() -> int:
    cfg = load_config(read_env(env_file_path()))
    setup_logging(cfg)
    for warning in cfg.warnings:
        log.warning("Config: %s", warning)
    log.info("Server starting (PID %d) on %s:%d, device %s, model %s", os.getpid(), cfg.host, cfg.port,
             cfg.device, cfg.model)
    import uvicorn

    engine = Engine(cfg)
    threading.Thread(target=engine.load, name="model-load", daemon=True).start()
    uvicorn.run(create_app(engine), host=cfg.host, port=cfg.port, log_config=None, access_log=False)
    log.info("Server stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
