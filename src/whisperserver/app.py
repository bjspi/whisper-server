"""Tray application: single instance, watchdog thread, Qt tray + settings window."""

from __future__ import annotations

import argparse
import ctypes
import logging
import logging.handlers
import os
import sys
import threading
from pathlib import Path

from whisperserver import __version__
from whisperserver.config import ensure_models_dir, env_file_path, load_config, read_env

log = logging.getLogger("whisperserver")
MUTEX_NAME = "Local\\WhisperServerTray"
ERROR_ALREADY_EXISTS = 183


def single_instance() -> object | None:
    if sys.platform != "win32":
        return object()
    handle = ctypes.windll.kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if ctypes.windll.kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
        return None
    return handle


def setup_logging(log_dir: Path, level: str) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(log_dir / "tray.log", maxBytes=1_000_000, backupCount=3,
                                                   encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(level)
    if sys.stderr is not None:
        root.addHandler(logging.StreamHandler())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="whisperserver", description="Local Whisper server with tray and watchdog")
    parser.add_argument("command", nargs="?", default="run",
                        choices=("run", "stop", "update", "autostart", "uninstall", "version"),
                        help="run (default): start the tray, stop, update, autostart on|off, uninstall, version")
    parser.add_argument("state", nargs="?", choices=("on", "off"), help="for 'autostart'")
    parser.add_argument("--env-file", help="settings file (default: %%LOCALAPPDATA%%\\WhisperServer\\.env)")
    parser.add_argument("--check", action="store_true", help="validate the configuration and exit")
    parser.add_argument("--no-restart", action="store_true", help="'update': do not restart the tray afterwards")
    parser.add_argument("--foreground", action="store_true", help="run the tray in this console (logs to stderr)")
    parser.add_argument("--wait-pid", type=int, help=argparse.SUPPRESS)  # restart: wait for the old tray
    args = parser.parse_args(argv)
    if args.command != "run":
        from whisperserver import cli

        if args.command == "version":
            print(f"whisperserver {__version__} ({cli.install_kind()} install)")
            return 0
        if args.command == "autostart":
            if args.state is None:
                parser.error("autostart needs 'on' or 'off'")
            return cli.set_autostart(args.state)
        return {"stop": cli.stop, "uninstall": cli.uninstall,
                "update": lambda: cli.update(restart=not args.no_restart)}[args.command]()
    if args.wait_pid:
        import psutil

        try:
            psutil.Process(args.wait_pid).wait(timeout=60)
        except (psutil.Error, psutil.TimeoutExpired):
            pass

    env_path = env_file_path(args.env_file)
    os.environ["WHISPER_ENV_FILE"] = str(env_path)  # the server child reads the same file
    cfg = load_config(read_env(env_path))
    if args.check:
        print(f"settings: {env_path}\nendpoint: {cfg.endpoint}\nmodel:    {cfg.model_path}\ndevice:   {cfg.device}")
        for warning in cfg.warnings:
            print(f"warning:  {warning}")
        return 1 if cfg.warnings else 0

    pythonw = Path(sys.executable).with_name("pythonw.exe")
    if (sys.platform == "win32" and not args.foreground and not args.wait_pid
            and Path(sys.executable).name.lower() == "python.exe" and pythonw.is_file()):
        import subprocess

        cmd = [str(pythonw), "-m", "whisperserver"] + (["--env-file", args.env_file] if args.env_file else [])
        subprocess.Popen(cmd, creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
                         close_fds=True)
        print(f"Whisper Server started in the tray - endpoint {cfg.endpoint}")
        return 0

    mutex = single_instance()
    if mutex is None:
        return 0  # already running

    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    ensure_models_dir(cfg.models_dir)
    setup_logging(cfg.log_dir, cfg.log_level)
    log.info("WhisperServer tray %s starting (settings %s)", __version__, env_path)
    for warning in cfg.warnings:
        log.warning("Config: %s", warning)

    if sys.platform == "win32":
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("WhisperServer.Tray")

    from PyQt6.QtWidgets import QApplication

    from whisperserver.ui.theme import app_icon, is_dark, palette, stylesheet
    from whisperserver.ui.tray import Tray, relaunch
    from whisperserver.watchdog import Watchdog

    app = QApplication(sys.argv[:1])
    app.setApplicationName("Whisper Server")
    app.setQuitOnLastWindowClosed(False)
    app.setStyle("Fusion")
    app.setWindowIcon(app_icon())
    dark = is_dark(app)
    app.setStyleSheet(stylesheet(dark, cfg.data_dir / "ui-cache"))

    watchdog = Watchdog(cfg)
    tray = Tray(watchdog, env_path, palette(dark))
    tray.quit_requested.connect(app.quit)
    restart = {"wanted": False}

    def restart_app():
        restart["wanted"] = True
        app.quit()

    tray.restart_app_requested.connect(restart_app)
    thread = threading.Thread(target=watchdog.run, name="watchdog", daemon=True)
    thread.start()

    try:
        code = app.exec()
    finally:
        log.info("Shutting down")
        tray.settings.benchmark.shutdown()
        tray.hide()
        watchdog.shutdown()
        thread.join(timeout=cfg.stop_timeout_s + 5)
        if restart["wanted"]:
            log.info("Restarting the tray")
            relaunch()
    return code


if __name__ == "__main__":
    sys.exit(main())
