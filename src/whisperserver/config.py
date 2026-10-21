"""Settings: %LOCALAPPDATA%\\WhisperServer\\.env (KEY=VALUE), overridable by WHISPER_* environment variables.

Models live in %LOCALAPPDATA%\\WhisperServer\\models (a source checkout with an existing <project>\\models folder
keeps using that one). The folder is marked with .nobackup so backup tools can skip it.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

ENV_PREFIX = "WHISPER_"
PROJECT_DIR = Path(__file__).resolve().parents[2]
DEVICES = ("GPU", "NPU", "CPU", "AUTO")

#: Selectable models (Hugging Face repo id, label). Any other OpenVINO Whisper repo id works as well.
MODELS: tuple[tuple[str, str], ...] = (
    ("OpenVINO/whisper-large-v3-turbo-int4-ov", "large-v3-turbo int4 - fastest (recommended)"),
    ("OpenVINO/whisper-large-v3-turbo-int8-ov", "large-v3-turbo int8"),
    ("OpenVINO/whisper-large-v3-turbo-fp16-ov", "large-v3-turbo fp16 - full precision"),
    ("OpenVINO/whisper-large-v3-int8-ov", "large-v3 int8 - slower, slightly more accurate"),
)
DEFAULT_MODEL = MODELS[0][0]


def data_dir() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "WhisperServer"


def default_models_dir(data: Path) -> Path:
    legacy = PROJECT_DIR / "models"
    if (PROJECT_DIR / "pyproject.toml").is_file() and legacy.is_dir():
        return legacy
    return data / "models"


def env_file_path(explicit: str | None = None) -> Path:
    return Path(explicit or os.environ.get("WHISPER_ENV_FILE") or data_dir() / ".env")


def read_env(path: Path, include_environ: bool = True) -> dict[str, str]:
    """KEY=VALUE lines; # comments and blank lines ignored. Environment variables win."""
    values: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError:
        text = ""
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.split(" #", 1)[0].strip().strip('"').strip("'")
        values[key.strip().upper()] = value
    if include_environ:
        values.update({k.upper(): v for k, v in os.environ.items()
                       if k.upper().startswith(ENV_PREFIX) and k.upper() != "WHISPER_ENV_FILE"})
    return values


def write_env(path: Path, updates: Mapping[str, str]) -> None:
    """Update KEY=VALUE lines in place (comments and unknown keys are kept), append new keys."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        lines = ["# WhisperServer settings (written by the settings window; WHISPER_* environment variables win)"]
    pending = dict(updates)
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("#") or "=" not in stripped:
            continue
        key = stripped.split("=", 1)[0].strip().upper()
        if key in pending:
            lines[index] = f"{key}={pending.pop(key)}"
    lines += [f"{key}={value}" for key, value in pending.items()]
    tmp = path.with_suffix(".tmp")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def model_dir_name(model: str) -> str:
    return model.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]


@dataclass
class Config:
    host: str = "127.0.0.1"
    port: int = 9017
    device: str = "GPU"
    model: str = DEFAULT_MODEL
    language: str = "de"
    vad: bool = True
    data_dir: Path = field(default_factory=data_dir)
    models_dir: Path = field(default_factory=lambda: default_models_dir(data_dir()))
    check_interval_s: float = 10.0
    deep_check_interval_s: float = 900.0
    http_timeout_s: float = 5.0
    deep_timeout_s: float = 60.0
    startup_timeout_s: float = 1800.0  # the first start downloads the model (0.5-1.6 GB)
    fail_threshold: int = 3
    restart_backoff_s: tuple[float, ...] = (0, 10, 30, 60, 120, 300)
    stop_timeout_s: float = 10.0
    log_level: str = "INFO"
    warnings: list[str] = field(default_factory=list)

    @property
    def log_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def model_path(self) -> Path:
        candidate = Path(self.model)
        return candidate if candidate.is_absolute() else self.models_dir / model_dir_name(self.model)

    @property
    def base_url(self) -> str:
        host = "127.0.0.1" if self.host in ("0.0.0.0", "") else self.host
        return f"http://{host}:{self.port}"

    @property
    def endpoint(self) -> str:
        return f"{self.base_url}/v1/audio/transcriptions"


def model_downloaded(path: Path) -> bool:
    return (path / "openvino_encoder_model.xml").is_file() and (path / "openvino_decoder_model.xml").is_file()


def ensure_models_dir(models_dir: Path) -> None:
    """Create the models folder with a .nobackup marker (e.g. restic --exclude-if-present .nobackup)."""
    models_dir.mkdir(parents=True, exist_ok=True)
    marker = models_dir / ".nobackup"
    if not marker.exists():
        marker.write_text("Downloaded Whisper models - backup tools may skip this folder.\n", encoding="utf-8")


def _number(values, key, default, cast, warnings, minimum=None, maximum=None):
    raw = values.get(key)
    if raw in (None, ""):
        return default
    try:
        number = cast(raw)
    except ValueError:
        warnings.append(f"{key}={raw!r} is not a number, using {default}")
        return default
    if (minimum is not None and number < minimum) or (maximum is not None and number > maximum):
        warnings.append(f"{key}={raw} out of range, using {default}")
        return default
    return number


def load_config(values: Mapping[str, str]) -> Config:
    cfg = Config()
    w = cfg.warnings
    cfg.host = values.get("WHISPER_HOST") or cfg.host
    cfg.port = _number(values, "WHISPER_PORT", cfg.port, int, w, 1024, 65535)
    device = (values.get("WHISPER_DEVICE") or cfg.device).upper()
    if device in DEVICES:
        cfg.device = device
    else:
        w.append(f"WHISPER_DEVICE={device!r} unknown (use {', '.join(DEVICES)}), using {cfg.device}")
    cfg.model = values.get("WHISPER_MODEL") or cfg.model
    cfg.language = (values.get("WHISPER_LANGUAGE") or cfg.language).lower()
    cfg.vad = values.get("WHISPER_VAD", "1").strip().lower() not in ("0", "false", "no", "off")
    if values.get("WHISPER_DATA_DIR"):
        cfg.data_dir = Path(values["WHISPER_DATA_DIR"])
    cfg.models_dir = Path(values["WHISPER_MODELS_DIR"]) if values.get("WHISPER_MODELS_DIR") \
        else default_models_dir(cfg.data_dir)
    cfg.check_interval_s = _number(values, "WHISPER_CHECK_INTERVAL_S", cfg.check_interval_s, float, w, 2)
    cfg.deep_check_interval_s = _number(values, "WHISPER_DEEP_CHECK_INTERVAL_S", cfg.deep_check_interval_s,
                                        float, w, 30)
    cfg.startup_timeout_s = _number(values, "WHISPER_STARTUP_TIMEOUT_S", cfg.startup_timeout_s, float, w, 30)
    level = (values.get("WHISPER_LOG_LEVEL") or cfg.log_level).upper()
    cfg.log_level = level if level in ("DEBUG", "INFO", "WARNING", "ERROR") else cfg.log_level
    if cfg.host not in ("127.0.0.1", "localhost", "::1"):
        w.append(f"WHISPER_HOST={cfg.host} exposes the server beyond this computer")
    return cfg
