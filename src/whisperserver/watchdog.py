"""The watchdog: owns the server process and runs the health loop on its own thread.

Only the health thread starts or stops processes; the tray just queues requests and reads state.
"""

from __future__ import annotations

import json
import logging
import subprocess
import threading
import time
import urllib.request
from typing import Callable

import psutil

from whisperserver import process
from whisperserver.config import Config

log = logging.getLogger(__name__)

STARTING, LOADING, OK, DOWN, CONFLICT = "starting", "loading", "ok", "down", "conflict"
REQUEST_RESTART = "restart"
REQUEST_DEEP_CHECK = "deep_check"

# Direct connection: a system proxy must never see (or break) localhost traffic.
_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def get_health(base_url: str, timeout: float, deep: bool = False) -> dict:
    url = f"{base_url}/health" + ("?deep=1" if deep else "")
    with _opener.open(url, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def backoff_remaining(attempts: int, last_start: float | None, now: float, steps: tuple[float, ...]) -> float:
    if not attempts or last_start is None:
        return 0.0
    delay = steps[min(attempts, len(steps) - 1)]
    return max(0.0, last_start + delay - now)


class Watchdog:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.proc: subprocess.Popen | None = None
        self.started_at: float | None = None
        self.attempts = 0
        self.last_auto_start: float | None = None
        self.fail_streak = 0
        self.last_deep: float = 0.0
        self.deep_due = False
        self.state = STARTING
        self.detail = "Watchdog starting"
        self.last_check = ""
        self.last_latency: float | None = None
        self.on_change: Callable[[], None] = lambda: None
        self._wake = threading.Event()
        self._stopping = threading.Event()
        self._lock = threading.Lock()
        self._requests: list[str] = []
        self._pending_cfg: Config | None = None

    # --- thread-safe API for the tray
    def request(self, what: str) -> None:
        with self._lock:
            self._requests.append(what)
        self._wake.set()

    def shutdown(self) -> None:
        self._stopping.set()
        self._wake.set()

    def apply_config(self, cfg: Config) -> None:
        """Switch to new settings (port, model, device ...) and restart the server."""
        with self._lock:
            self._pending_cfg = cfg
            self._requests.append(REQUEST_RESTART)
        self._wake.set()

    # --- server process (health thread only)
    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def start_server(self, reason: str) -> None:
        cmd = process.server_command()
        log.info("Starting server (%s): %s", reason, subprocess.list2cmdline(cmd))
        self.started_at = time.monotonic()
        self.fail_streak = 0
        try:
            self.proc = subprocess.Popen(
                cmd, cwd=self.cfg.data_dir, env=process.child_environment(),
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            log.info("Server started, PID %d", self.proc.pid)
        except OSError as exc:
            self.proc = None
            log.error("Starting the server failed: %s", exc)

    def stop_server(self) -> None:
        if self.proc is None:
            return
        if self.proc.poll() is None:
            log.info("Stopping server (PID %d)", self.proc.pid)
            try:
                process.stop_processes(process.process_tree(psutil.Process(self.proc.pid)), self.cfg.stop_timeout_s)
            except psutil.Error:
                pass
        self.proc = None
        self.started_at = None

    def _restart(self, reason: str) -> bool:
        """Restart with backoff. Returns False while the backoff is still running."""
        wait = backoff_remaining(self.attempts, self.last_auto_start, time.monotonic(), self.cfg.restart_backoff_s)
        if wait > 0:
            self.detail += f", restart in {wait:.0f} s"
            return False
        self.stop_server()
        self.start_server(f"{reason}, attempt {self.attempts + 1}")
        self.attempts += 1
        self.last_auto_start = time.monotonic()
        return True

    # --- health loop
    def run(self) -> None:
        last_wall = time.time()
        try:
            while not self._stopping.is_set():
                self._wake.clear()
                gap = time.time() - last_wall
                if gap > self.cfg.check_interval_s + 30:
                    log.info("Clock jumped %.0f s since the last tick (standby/hibernate?) - deep check", gap)
                    self.deep_due = True
                last_wall = time.time()
                self._handle_requests()
                if not self._stopping.is_set():
                    try:
                        self.tick()
                    except Exception:  # noqa: BLE001 - the watchdog must never die
                        log.exception("Health tick failed")
                self._wake.wait(self.cfg.check_interval_s)
        finally:
            self.stop_server()

    def _handle_requests(self) -> None:
        with self._lock:
            requests, self._requests = self._requests, []
            new_cfg, self._pending_cfg = self._pending_cfg, None
        for req in requests:
            if req == REQUEST_RESTART:
                log.info("Manual restart" if new_cfg is None else "Settings changed - restarting server")
                self.attempts, self.last_auto_start = 0, None
                self.stop_server()
                if new_cfg is not None:
                    self.cfg, new_cfg = new_cfg, None
                self.last_deep, self.last_latency = 0.0, None
                self.start_server("manual")
            elif req == REQUEST_DEEP_CHECK:
                self.deep_due = True

    def _set(self, state: str, detail: str) -> None:
        if self.cfg.warnings:
            detail += " - Konfigurationswarnung, siehe Log"
        if (state, detail) != (self.state, self.detail):
            log.info("State: %s - %s", state, detail)
        self.state, self.detail = state, detail
        self.last_check = time.strftime("%H:%M:%S")
        self.on_change()

    def tick(self) -> None:
        cfg = self.cfg
        if self.proc is not None and not self.alive():
            log.warning("Server process (PID %d) exited with code %s", self.proc.pid, self.proc.returncode)
            self.proc, self.started_at = None, None

        if not self.alive():
            owner = process.port_owner(cfg.port)
            if owner is not None:
                try:
                    owner_proc = psutil.Process(owner)
                    if process.is_our_server(owner_proc):
                        log.info("Stopping orphaned server PID %d on port %d", owner, cfg.port)
                        process.stop_processes(process.process_tree(owner_proc), cfg.stop_timeout_s)
                        owner = None
                    else:
                        name = owner_proc.name()
                except psutil.Error:
                    owner, name = None, ""
            if owner is not None:
                self._set(CONFLICT, f"Port {cfg.port} in use by {name} (PID {owner})")
                return
            self.detail = "Server not running"
            if self._restart("not running"):
                self._set(STARTING, "Starting server")
            else:
                self._set(DOWN, self.detail)
            return

        since = time.monotonic() - (self.started_at or time.monotonic())
        try:
            health = get_health(cfg.base_url, cfg.http_timeout_s)
        except Exception as exc:  # noqa: BLE001
            if since < 60:
                self._set(STARTING, "waiting for HTTP port")
                return
            self.fail_streak += 1
            log.warning("Health check failure #%d: %s", self.fail_streak, exc)
            if self.fail_streak >= cfg.fail_threshold:
                self.detail = "Server not responding"
                self._restart("not responding")
                self._set(DOWN, self.detail)
            else:
                self._set(self.state, f"no response ({self.fail_streak}x)")
            return

        if health.get("pid") not in process.tree_pids(self.proc.pid):
            self._set(CONFLICT, f"Port {cfg.port} answered by another process (PID {health.get('pid')})")
            return
        self.fail_streak = 0
        status = health.get("status")
        if status in ("downloading", "loading"):
            if since > cfg.startup_timeout_s:
                self.detail = f"{status} took longer than {cfg.startup_timeout_s:.0f} s"
                self._restart("startup timeout")
                self._set(DOWN, self.detail)
            else:
                self._set(LOADING, "downloading model (first start)" if status == "downloading"
                          else f"loading model on {cfg.device}")
            return
        if status != "ready":
            self.detail = f"Model error: {health.get('error', status)}"[:90]
            self._restart("model error")
            self._set(DOWN, self.detail)
            return

        if self.deep_due or time.monotonic() - self.last_deep > cfg.deep_check_interval_s:
            try:
                deep = get_health(cfg.base_url, cfg.deep_timeout_s, deep=True)
                self.last_latency = deep.get("deep_s")
                self.last_deep, self.deep_due = time.monotonic(), False
                log.info("Deep check OK: inference %.2f s", self.last_latency or 0)
            except Exception as exc:  # noqa: BLE001 - e.g. GPU hung after resume
                log.warning("Deep check failed: %s", exc)
                self.deep_due = False
                self.detail = "Inference hangs"
                self._restart("inference hangs")
                self._set(DOWN, self.detail)
                return

        if self.attempts:
            log.info("Server healthy again, backoff reset")
        self.attempts, self.last_auto_start = 0, None
        self._set(OK, f"ready on port {cfg.port} ({health.get('model')}, {cfg.device})")
