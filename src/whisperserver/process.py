"""Process helpers: start command, process trees, port owner, orphan detection."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

import psutil

log = logging.getLogger(__name__)

SERVER_MODULE = "whisperserver.server"


def server_command() -> list[str]:
    exe = Path(sys.executable)
    pythonw = exe.with_name("pythonw.exe")
    return [str(pythonw if pythonw.is_file() else exe), "-m", SERVER_MODULE]


def is_our_server(proc: psutil.Process) -> bool:
    """A server process started by any WhisperServer tray (e.g. orphaned after a tray crash)."""
    try:
        cmd = [a.lower() for a in proc.cmdline()]
        return any(a == "-m" and nxt == SERVER_MODULE for a, nxt in zip(cmd, cmd[1:]))
    except psutil.Error:
        return False


def process_tree(proc: psutil.Process) -> list[psutil.Process]:
    try:
        return [proc] + proc.children(recursive=True)
    except psutil.Error:
        return [proc]


def tree_pids(pid: int) -> set[int]:
    try:
        return {p.pid for p in process_tree(psutil.Process(pid))}
    except psutil.Error:
        return set()


def stop_processes(procs: list[psutil.Process], timeout: float) -> None:
    procs = [p for p in procs if p.is_running()]
    for proc in procs:
        try:
            proc.terminate()
        except psutil.Error:
            pass
    _, alive = psutil.wait_procs(procs, timeout=timeout)
    for proc in alive:
        try:
            proc.kill()
        except psutil.Error:
            pass
    psutil.wait_procs(alive, timeout=timeout)


def port_owner(port: int) -> int | None:
    try:
        for conn in psutil.net_connections(kind="tcp"):
            if conn.status == psutil.CONN_LISTEN and conn.laddr and conn.laddr.port == port and conn.pid:
                return conn.pid
    except (psutil.Error, OSError) as exc:
        log.debug("net_connections failed: %s", exc)
    return None


def child_environment() -> dict[str, str]:
    env = dict(os.environ)
    # The server only talks to localhost; Hugging Face downloads still use the system proxy settings.
    env.setdefault("NO_PROXY", "127.0.0.1,localhost")
    env["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return env
