"""Tiny HTTP client for the local server (no proxy, multipart upload)."""

from __future__ import annotations

import json
import time
import urllib.request
import uuid
from pathlib import Path

_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def transcribe(endpoint: str, audio: Path, language: str = "de", timeout: float = 300) -> tuple[str, float]:
    """POST the file to /v1/audio/transcriptions. Returns (text, round-trip seconds)."""
    boundary = uuid.uuid4().hex
    parts = []
    for name, value in (("model", "whisper-large-v3-turbo"), ("language", language), ("response_format", "json")):
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
    parts.append((f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{audio.name}"\r\n'
                  "Content-Type: application/octet-stream\r\n\r\n").encode() + audio.read_bytes() + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    req = urllib.request.Request(endpoint, data=b"".join(parts), method="POST",
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    start = time.perf_counter()
    with _opener.open(req, timeout=timeout) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    return body.get("text", ""), time.perf_counter() - start
