"""Maintenance commands: stop, update, autostart, uninstall (work for uv tool, pipx and source checkouts)."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import psutil

from whisperserver import autostart
from whisperserver.config import PROJECT_DIR

PACKAGE = "whisperserver"


def _is_whisperserver(cmdline: list[str]) -> bool:
    args = [a.lower() for a in cmdline]
    if any(a == "-m" and nxt in (PACKAGE, f"{PACKAGE}.server") for a, nxt in zip(args, args[1:])):
        return True
    return any(Path(a).name in (f"{PACKAGE}-gui.exe", f"{PACKAGE}-gui", f"{PACKAGE}.exe") and
               len(args) <= 3 for a in args[:2])


def running_processes() -> list[psutil.Process]:
    """Tray and server processes, excluding this command and its launchers."""
    me = psutil.Process()
    skip = {me.pid} | {p.pid for p in me.parents()}
    found = []
    for proc in psutil.process_iter(["pid", "name"]):
        if proc.pid in skip or not (proc.info["name"] or "").lower().startswith(("python", PACKAGE)):
            continue
        try:
            if _is_whisperserver(proc.cmdline()):
                found.append(proc)
        except psutil.Error:
            continue
    return found


def stop(quiet: bool = False) -> int:
    from whisperserver.process import process_tree, stop_processes

    procs = running_processes()
    tree = {p.pid: p for root in procs for p in process_tree(root)}
    stop_processes(list(tree.values()), timeout=10)
    if not quiet:
        print(f"Stopped {len(procs)} Whisper Server process(es)." if procs else "Whisper Server is not running.")
    return 0


def install_kind() -> str:
    prefix = Path(sys.prefix)
    if (prefix / "uv-receipt.toml").is_file():
        return "uv"
    if (prefix / "pipx_metadata.json").is_file():
        return "pipx"
    if (PROJECT_DIR / ".git").exists():
        return "git"
    return "unknown"


def _tray_command() -> list[str]:
    exe = Path(sys.executable)
    pythonw = exe.with_name("pythonw.exe")
    return [str(pythonw if pythonw.is_file() else exe), "-m", PACKAGE]


def update_command(kind: str) -> list[str] | None:
    if kind == "uv" and shutil.which("uv"):
        return ["uv", "tool", "upgrade", "--reinstall", PACKAGE]
    if kind == "pipx" and shutil.which("pipx"):
        base = Path(getattr(sys, "_base_executable", sys.executable))
        python = base.with_name("python.exe") if base.with_name("python.exe").is_file() else base
        return ["pipx", "reinstall", "--python", str(python), PACKAGE]
    if kind == "git" and shutil.which("git"):
        return ["git", "-C", str(PROJECT_DIR), "pull", "--ff-only"]
    return None


def update(restart: bool = True) -> int:
    kind = install_kind()
    cmd = update_command(kind)
    if cmd is None:
        print(f"Cannot update automatically (install type: {kind}). Reinstall with "
              "'uv tool install --force git+https://github.com/bjspi/whisper-server'.")
        return 1
    was_running = bool(running_processes())
    stop(quiet=True)
    steps = [subprocess.list2cmdline(cmd)]
    if kind == "git" and shutil.which("uv"):
        steps.append(subprocess.list2cmdline(["uv", "pip", "install", "--python", sys.executable, "-e",
                                              str(PROJECT_DIR)]))
    script = " && ".join(steps)
    if restart and was_running:
        script += " && start \"\" " + subprocess.list2cmdline(_tray_command())
    print(f"Updating Whisper Server ({kind}): {script}")
    if kind == "git":
        return subprocess.call(script, shell=True)
    # uv/pipx replace this very environment, so the update runs after this process has exited.
    full = f"timeout /t 2 /nobreak >nul & ({script}) || pause"
    subprocess.Popen(["cmd", "/c", full], creationflags=subprocess.CREATE_NEW_CONSOLE, close_fds=True,
                     cwd=os.path.expanduser("~"))
    return 0


def set_autostart(state: str) -> int:
    autostart.set_enabled(state == "on")
    print(f"Autostart {'enabled' if autostart.is_enabled() else 'disabled'}.")
    return 0


def uninstall() -> int:
    stop()
    autostart.set_enabled(False)
    kind = install_kind()
    remove = {"uv": "uv tool uninstall whisperserver", "pipx": "pipx uninstall whisperserver"}.get(
        kind, "delete the cloned folder")
    print("Autostart removed. To finish, run:\n"
          f"  {remove}\n"
          "Settings, logs and models stay in %LOCALAPPDATA%\\WhisperServer - delete that folder to remove them too.")
    return 0
