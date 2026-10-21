"""System tray icon and its context menu, laid out like PathScout/WinLauncher:
header (logo, name, status) · actions · settings & autostart · about · restart / quit."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtGui import QAction, QGuiApplication, QIcon
from PyQt6.QtWidgets import (
    QHBoxLayout, QLabel, QMessageBox, QSystemTrayIcon, QVBoxLayout, QWidget, QWidgetAction,
)

from whisperserver import __version__, autostart
from whisperserver.ui.icons import RoundedMenu, line_icon
from whisperserver.ui.settings import STATE_LABELS, SettingsWindow, open_path
from whisperserver.ui.theme import app_icon

HEADER_ICON_SIZE = 30


class Tray(QObject):
    changed = pyqtSignal()  # emitted from the watchdog thread, delivered queued on the GUI thread
    quit_requested = pyqtSignal()
    restart_app_requested = pyqtSignal()

    def __init__(self, watchdog, env_path: Path, colors: dict[str, str]):
        super().__init__()
        self.watchdog = watchdog
        self.colors = colors
        self.settings = SettingsWindow(watchdog, env_path, colors)
        self._last_state: str | None = None

        self.icon = QSystemTrayIcon(app_icon("starting"), self)
        self.menu = RoundedMenu()
        self.menu.setObjectName("tray")
        self.status = QLabel()
        self.status.setObjectName("trayStatus")
        self.menu.addAction(self._header())
        self.menu.addSeparator()
        self._add("Test last recording", self._test_latest, "test")
        self._add("Copy endpoint URL", self._copy_endpoint, "copy")
        self._add("Self-test", lambda: watchdog.request("deep_check"), "pulse")
        self._add("Restart server", lambda: watchdog.request("restart"), "restart")
        self.menu.addSeparator()
        self._add("Settings …", self.open_settings, "settings")
        # The check mark is drawn as an icon, so it lines up with the other icons.
        self.autostart = self._add("Start with Windows", self._toggle_autostart)
        self.autostart.setCheckable(True)
        self._add("Open logs", lambda: open_path(watchdog.cfg.log_dir), "folder")
        self.menu.addSeparator()
        self._add("About Whisper Server", self._about, "info")
        self.menu.addSeparator()
        self._add("Restart Whisper Server", self.restart_app_requested.emit, "power")
        self._add("Quit Whisper Server", self.quit_requested.emit, "quit")
        self.menu.aboutToShow.connect(self._sync_autostart)
        self._sync_autostart()
        self.icon.setContextMenu(self.menu)
        self.icon.activated.connect(self._activated)

        self.changed.connect(self._refresh)
        watchdog.on_change = self.changed.emit
        self._refresh()
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.icon.show()

    # --- menu
    def _header(self) -> QWidgetAction:
        header = QWidget()
        header.setObjectName("trayHeader")
        layout = QHBoxLayout(header)
        layout.setContentsMargins(12, 8, 16, 6)
        layout.setSpacing(10)
        logo = QLabel()
        logo.setPixmap(app_icon().pixmap(HEADER_ICON_SIZE, HEADER_ICON_SIZE))
        texts = QVBoxLayout()
        texts.setSpacing(0)
        name = QLabel("Whisper Server")
        name.setObjectName("trayTitle")
        texts.addWidget(name)
        texts.addWidget(self.status)
        layout.addWidget(logo)
        layout.addLayout(texts, 1)
        action = QWidgetAction(self.menu)
        action.setDefaultWidget(header)
        return action

    def _add(self, text: str, slot, icon: str | None = None) -> QAction:
        action = self.menu.addAction(text)
        if icon is not None:
            action.setIcon(line_icon(icon, self.colors["muted"]))
        action.triggered.connect(slot)
        return action

    def _show_check(self, checked: bool) -> None:
        # A null icon keeps the icon column free, so the text stays aligned.
        self.autostart.setIcon(line_icon("check", self.colors["accent"]) if checked else QIcon())

    def _sync_autostart(self) -> None:
        try:
            enabled = autostart.is_enabled()
        except OSError:
            self.autostart.setEnabled(False)
            return
        self.autostart.blockSignals(True)
        self.autostart.setChecked(enabled)
        self.autostart.blockSignals(False)
        self._show_check(enabled)

    def _toggle_autostart(self, enabled: bool) -> None:
        try:
            autostart.set_enabled(enabled)
        except OSError as exc:
            self.icon.showMessage("Whisper Server", f"Could not change autostart: {exc}",
                                  QSystemTrayIcon.MessageIcon.Warning, 4000)
        self._sync_autostart()
        self.settings.autostart_switch.setChecked(self.autostart.isChecked())

    # --- state
    def _refresh(self) -> None:
        wd = self.watchdog
        label = STATE_LABELS.get(wd.state, wd.state)
        compact = {"ok": f"Port {wd.cfg.port} · {wd.cfg.device}"}.get(wd.state, wd.detail)
        self.status.setText(f"{label} · {compact}"[:48])
        self.icon.setToolTip(f"Whisper Server - {label}\n{wd.detail}"[:127])
        if wd.state != self._last_state:
            self.icon.setIcon(app_icon(wd.state))
            self._last_state = wd.state
        if self.settings.isVisible():
            self.settings.refresh_status()

    def _activated(self, reason) -> None:
        # A double-click also reports Trigger first; reacting to both would open twice.
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.open_settings()

    # --- actions
    def open_settings(self) -> None:
        if not self.settings.isVisible():
            self.settings.load_values()
        self.settings.refresh_status()
        self.settings.show()
        self.settings.raise_()
        self.settings.activateWindow()

    def _test_latest(self) -> None:
        self.open_settings()
        self.settings.run_latest_test()

    def _copy_endpoint(self) -> None:
        QGuiApplication.clipboard().setText(self.watchdog.cfg.endpoint)
        self.icon.showMessage("Whisper Server", f"Copied: {self.watchdog.cfg.endpoint}",
                              QSystemTrayIcon.MessageIcon.Information, 2500)

    def _about(self) -> None:
        box = QMessageBox()
        box.setWindowTitle("About Whisper Server")
        box.setIconPixmap(app_icon().pixmap(48, 48))
        box.setText(f"<b>Whisper Server {__version__}</b>")
        box.setInformativeText(
            "Local speech recognition - Whisper large-v3-turbo on OpenVINO.\n"
            "Your audio never leaves this PC.\n\n"
            f"Endpoint: {self.watchdog.cfg.endpoint}")
        box.exec()

    def hide(self) -> None:
        self.icon.hide()


def relaunch() -> None:
    """Start a fresh tray that waits for this process to exit (single-instance mutex)."""
    exe = Path(sys.executable)
    pythonw = exe.with_name("pythonw.exe")
    import os

    subprocess.Popen([str(pythonw if pythonw.is_file() else exe), "-m", "whisperserver", "--wait-pid", str(os.getpid())],
                     creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP, close_fds=True)
