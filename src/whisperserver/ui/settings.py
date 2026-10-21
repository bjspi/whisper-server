"""Settings window in WhisperTyper's modern layout: sidebar navigation, page header, cards, footer."""

from __future__ import annotations

import os
import threading
import wave
from pathlib import Path

from PyQt6.QtCore import QObject, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPlainTextEdit,
    QPushButton, QScrollArea, QSpinBox, QStackedWidget, QVBoxLayout, QWidget,
)

from whisperserver import __version__, autostart, client
from whisperserver.config import (
    DEVICES, MODELS, ensure_models_dir, load_config, model_dir_name, model_downloaded, read_env, write_env,
)
from whisperserver.ui.icons import line_icon
from whisperserver.ui.rows import COMBO_WIDTH, NUMBER_WIDTH, Card, card_title, controls
from whisperserver.ui.theme import app_icon

STATE_LABELS = {
    "ok": "Ready", "loading": "Loading model", "starting": "Starting", "down": "Down", "conflict": "Port conflict",
}
DEVICE_LABELS = {
    "GPU": "GPU - Intel Arc (fastest)", "NPU": "NPU - unstable, ~7 min load", "CPU": "CPU - slow",
    "AUTO": "AUTO - OpenVINO decides",
}
PAGES = (
    ("server", "Server", "Status, endpoint and port of the local Whisper server"),
    ("model", "Model", "Which Whisper model runs on which device"),
    ("test", "Test", "Transcribe a recording locally and measure the time"),
    ("info", "Info", "Version, logs and settings file"),
)


def open_path(folder: Path) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    os.startfile(str(folder))  # noqa: S606 - opens Explorer


def latest_whispertyper_recording() -> Path | None:
    temp = Path(os.environ.get("TEMP", Path.home()))
    files = sorted(temp.glob("whispertyper_recording_*.wav"), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def wav_seconds(path: Path) -> float | None:
    try:
        with wave.open(str(path)) as w:
            return w.getnframes() / float(w.getframerate())
    except (wave.Error, OSError, EOFError):
        return None


class _Bridge(QObject):
    done = pyqtSignal(str, float, str)


class SettingsWindow(QWidget):
    def __init__(self, watchdog, env_path: Path, colors: dict[str, str]):
        super().__init__()
        self.watchdog = watchdog
        self.env_path = env_path
        self.colors = colors
        self._bridge = _Bridge()
        self._bridge.done.connect(self._test_done)
        self._test_file: Path | None = None
        self.setWindowTitle("Whisper Server - Settings")
        self.setWindowIcon(app_icon())
        self.resize(920, 700)
        self.setMinimumSize(780, 520)

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._sidebar())

        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(0)
        header = QVBoxLayout()
        header.setContentsMargins(32, 24, 32, 4)
        header.setSpacing(2)
        self.page_title = QLabel()
        self.page_title.setObjectName("pageTitle")
        self.page_subtitle = QLabel()
        self.page_subtitle.setObjectName("pageSubtitle")
        header.addWidget(self.page_title)
        header.addWidget(self.page_subtitle)
        right.addLayout(header)

        self.stack = QStackedWidget()
        for builder in (self._page_server, self._page_model, self._page_test, self._page_info):
            self.stack.addWidget(self._scroll(builder()))
        right.addWidget(self.stack, 1)
        right.addWidget(self._footer())
        root.addLayout(right, 1)

        self.nav.currentRowChanged.connect(self._select_page)
        self.nav.setCurrentRow(0)
        self.load_values()
        self.refresh_status()

    # --- layout
    def _sidebar(self) -> QWidget:
        side = QFrame()
        side.setObjectName("sidebar")
        side.setFixedWidth(210)
        layout = QVBoxLayout(side)
        layout.setContentsMargins(14, 20, 14, 14)
        layout.setSpacing(4)
        brand = QHBoxLayout()
        brand.setSpacing(10)
        logo = QLabel()
        logo.setPixmap(app_icon().pixmap(34, 34))
        brand.addWidget(logo)
        names = QVBoxLayout()
        names.setSpacing(0)
        name = QLabel("Whisper Server")
        name.setObjectName("brandName")
        version = QLabel(f"Version {__version__} · local")
        version.setObjectName("brandVersion")
        names.addWidget(name)
        names.addWidget(version)
        brand.addLayout(names, 1)
        layout.addLayout(brand)
        layout.addSpacing(18)
        self.nav = QListWidget()
        self.nav.setObjectName("nav")
        self.nav.setIconSize(QSize(18, 18))
        self.nav.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        for key, title, _ in PAGES:
            icon = {"server": "server", "model": "model", "test": "test", "info": "info"}[key]
            item = QListWidgetItem(line_icon(icon, self.colors["nav_text"], self.colors["nav_selected"]), title)
            item.setSizeHint(QSize(0, 38))
            self.nav.addItem(item)
        layout.addWidget(self.nav, 1)
        return side

    def _scroll(self, page: QWidget) -> QScrollArea:
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.Shape.NoFrame)
        area.setWidget(page)
        return area

    def _page(self) -> tuple[QWidget, QVBoxLayout]:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(32, 0, 32, 24)
        layout.setSpacing(0)
        return page, layout

    def _footer(self) -> QWidget:
        footer = QFrame()
        footer.setObjectName("footer")
        layout = QHBoxLayout(footer)
        layout.setContentsMargins(24, 12, 24, 12)
        self.footer_hint = QLabel("")
        self.footer_hint.setObjectName("rowDescription")
        layout.addWidget(self.footer_hint, 1)
        close = QPushButton("Close")
        close.clicked.connect(self.close)
        self.save_button = QPushButton("Save")
        self.save_button.setObjectName("primary")
        self.save_button.clicked.connect(self.save)
        layout.addWidget(close)
        layout.addWidget(self.save_button)
        return footer

    def _select_page(self, index: int) -> None:
        _, title, subtitle = PAGES[index]
        self.page_title.setText(title)
        self.page_subtitle.setText(subtitle)
        self.stack.setCurrentIndex(index)

    def show_page(self, key: str) -> None:
        self.nav.setCurrentRow([p[0] for p in PAGES].index(key))

    # --- pages
    def _page_server(self) -> QWidget:
        page, layout = self._page()
        layout.addWidget(card_title("Status"))
        status = Card()
        self.state_label = QLabel()
        self.state_row = status.row("State", "", self.state_label)
        self.latency_label = QLabel("-")
        status.row("Self-test", "Last mini transcription by the watchdog (checks that the GPU still works after "
                   "standby).", self.latency_label)
        restart = QPushButton("Restart")
        restart.clicked.connect(lambda: self.watchdog.request("restart"))
        deep = QPushButton("Self-test now")
        deep.clicked.connect(lambda: self.watchdog.request("deep_check"))
        status.row("Actions", "The watchdog restarts the server automatically after a crash, hang or "
                   "standby.", controls(deep, restart))
        layout.addWidget(status)

        layout.addWidget(card_title("Connection"))
        conn = Card()
        self.endpoint_label = QLabel()
        self.endpoint_label.setObjectName("mono")
        self.endpoint_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        copy = QPushButton("Copy")
        copy.setIcon(line_icon("copy", self.colors["text"]))
        copy.clicked.connect(self._copy_endpoint)
        conn.row("Endpoint", "OpenAI-compatible, reachable from this PC only.",
                 controls(self.endpoint_label, copy))
        self.port_spin = QSpinBox()
        self.port_spin.setRange(1024, 65535)
        self.port_spin.setFixedWidth(NUMBER_WIDTH)
        conn.row("Port", "Default 9017. Changing it restarts the server.", self.port_spin)
        layout.addWidget(conn)

        layout.addWidget(card_title("System"))
        system = Card()
        self.autostart_switch = QCheckBox()
        system.row("Start with Windows", "Start tray and server when you sign in.", self.autostart_switch)
        layout.addWidget(system)
        layout.addStretch(1)
        return page

    def _page_model(self) -> QWidget:
        page, layout = self._page()
        layout.addWidget(card_title("Model"))
        card = Card()
        self.model_combo = QComboBox()
        self.model_combo.setFixedWidth(COMBO_WIDTH + 60)
        card.row("Whisper model", "OpenVINO models from Hugging Face. Missing ones are downloaded once when you "
                 "save; after that everything runs offline.", self.model_combo)
        self.device_combo = QComboBox()
        self.device_combo.setFixedWidth(COMBO_WIDTH)
        for dev in DEVICES:
            self.device_combo.addItem(DEVICE_LABELS[dev], dev)
        card.row("Device", "Used by server and benchmark. GPU (Intel Arc) is the fastest.", self.device_combo)
        self.vad_switch = QCheckBox()
        card.row("Remove silence (VAD)", "Cuts pauses before recognition - faster, and prevents invented "
                 "sentences like »Vielen Dank.«", self.vad_switch)
        layout.addWidget(card)

        from whisperserver.ui.benchmark import BenchmarkPanel
        self.benchmark = BenchmarkPanel(self)
        layout.addWidget(self.benchmark)

        layout.addWidget(card_title("Storage"))
        storage = Card()
        folder = QPushButton("Open folder")
        folder.setIcon(line_icon("folder", self.colors["text"]))
        folder.clicked.connect(lambda: open_path(self.watchdog.cfg.models_dir))
        row = storage.row("Models folder", "", folder)
        row.description.setVisible(True)
        self.models_row = row
        layout.addWidget(storage)
        layout.addStretch(1)
        return page

    def _page_test(self) -> QWidget:
        page, layout = self._page()
        layout.addWidget(card_title("Recording"))
        card = Card()
        latest = QPushButton("Last WhisperTyper recording")
        latest.clicked.connect(self._pick_latest)
        browse = QPushButton("Choose file …")
        browse.clicked.connect(self._pick_file)
        self.test_file_row = card.row("Audio file", "No file chosen yet.", controls(latest, browse))
        self.test_button = QPushButton("Transcribe")
        self.test_button.setObjectName("primary")
        self.test_button.setEnabled(False)
        self.test_button.clicked.connect(self._run_test)
        self.test_time = QLabel("")
        self.test_row = card.row("Transcribe locally", "Your audio never leaves this PC.",
                                 controls(self.test_time, self.test_button, spacing=14))
        layout.addWidget(card)
        layout.addWidget(card_title("Result"))
        self.test_output = QPlainTextEdit()
        self.test_output.setReadOnly(True)
        self.test_output.setMinimumHeight(180)
        self.test_output.setPlaceholderText("The recognized text appears here.")
        layout.addWidget(self.test_output, 1)
        return page

    def _page_info(self) -> QWidget:
        page, layout = self._page()
        layout.addWidget(card_title("About"))
        card = Card()
        card.row("Whisper Server", f"Version {__version__} · OpenVINO GenAI · Whisper large-v3-turbo")
        logs = QPushButton("Open")
        logs.setIcon(line_icon("folder", self.colors["text"]))
        logs.clicked.connect(lambda: open_path(self.watchdog.cfg.log_dir))
        card.row("Logs", str(self.watchdog.cfg.log_dir), logs)
        env = QPushButton("Open")
        env.clicked.connect(self._open_env)
        card.row("Settings file", f"{self.env_path} - WHISPER_* environment variables take precedence.", env)
        layout.addWidget(card)
        layout.addWidget(card_title("Clients"))
        hint = Card()
        hint.row("WhisperTyper & co.", "Enter the URL from the »Server« page as the OpenAI-compatible transcription "
                 "endpoint. The API key is not checked. Exclude 127.0.0.1 from any proxy settings.")
        layout.addWidget(hint)
        layout.addStretch(1)
        return page

    # --- values
    def load_values(self) -> None:
        cfg = load_config(read_env(self.env_path))
        self.port_spin.setValue(cfg.port)
        self.device_combo.setCurrentIndex(max(0, self.device_combo.findData(cfg.device)))
        self.vad_switch.setChecked(cfg.vad)
        try:
            self.autostart_switch.setChecked(autostart.is_enabled())
        except OSError:
            self.autostart_switch.setEnabled(False)
        self._fill_models(cfg)
        self.models_row.description.setText(f"{cfg.models_dir}  (.nobackup marker for backup tools)")

    def _fill_models(self, cfg) -> None:
        self.model_combo.clear()
        entries = list(MODELS)
        if cfg.model not in [m for m, _ in entries]:
            entries.append((cfg.model, model_dir_name(cfg.model)))
        for repo, label in entries:
            path = Path(repo) if Path(repo).is_absolute() else cfg.models_dir / model_dir_name(repo)
            mark = "✓" if model_downloaded(path) else "↓"
            self.model_combo.addItem(f"{mark}  {label}", repo)
        self.model_combo.setCurrentIndex(max(0, self.model_combo.findData(cfg.model)))
        self.model_combo.setToolTip("✓ downloaded · ↓ downloaded on next start")

    def save(self) -> None:
        old = self.watchdog.cfg
        updates = {
            "WHISPER_PORT": str(self.port_spin.value()),
            "WHISPER_MODEL": self.model_combo.currentData(),
            "WHISPER_DEVICE": self.device_combo.currentData(),
            "WHISPER_VAD": "1" if self.vad_switch.isChecked() else "0",
        }
        write_env(self.env_path, updates)
        try:
            if self.autostart_switch.isEnabled() and self.autostart_switch.isChecked() != autostart.is_enabled():
                autostart.set_enabled(self.autostart_switch.isChecked())
        except OSError as exc:
            self.footer_hint.setText(f"Could not change autostart: {exc}")
            return
        cfg = load_config(read_env(self.env_path))
        ensure_models_dir(cfg.models_dir)
        changed = (cfg.port, cfg.model, cfg.device, cfg.vad) != (old.port, old.model, old.device, old.vad)
        if changed:
            self.watchdog.apply_config(cfg)
            self.footer_hint.setText("Saved - the server restarts with the new settings.")
        else:
            self.footer_hint.setText("Saved.")
        self.refresh_status()

    # --- status (called from the tray when the watchdog changes)
    def refresh_status(self) -> None:
        wd = self.watchdog
        self.state_label.setText(STATE_LABELS.get(wd.state, wd.state))
        self.state_label.setProperty("state", wd.state)
        self.state_label.style().unpolish(self.state_label)
        self.state_label.style().polish(self.state_label)
        self.state_row.description.setText(f"{wd.detail} · checked {wd.last_check or '-'}")
        self.state_row.description.setVisible(True)
        self.latency_label.setText(f"{wd.last_latency:.2f} s" if wd.last_latency is not None else "-")
        self.endpoint_label.setText(wd.cfg.endpoint)

    def _copy_endpoint(self) -> None:
        QGuiApplication.clipboard().setText(self.watchdog.cfg.endpoint)
        self.footer_hint.setText("Endpoint URL copied.")

    def _open_env(self) -> None:
        if not self.env_path.exists():
            write_env(self.env_path, {})
        os.startfile(str(self.env_path))  # noqa: S606

    # --- test page
    def _set_test_file(self, path: Path | None) -> None:
        self._test_file = path
        if path is None:
            self.test_file_row.description.setText("No WhisperTyper recording found in %TEMP%.")
        else:
            secs = wav_seconds(path)
            self.test_file_row.description.setText(path.name + (f"  ·  {secs:.1f} s audio" if secs else ""))
        self.test_button.setEnabled(path is not None)

    def _pick_latest(self) -> None:
        self._set_test_file(latest_whispertyper_recording())

    def _pick_file(self) -> None:
        name, _ = QFileDialog.getOpenFileName(self, "Choose audio file", os.environ.get("TEMP", ""),
                                              "Audio (*.wav *.mp3 *.m4a *.ogg *.flac *.webm);;All files (*)")
        if name:
            self._set_test_file(Path(name))

    def run_latest_test(self) -> None:
        self.show_page("test")
        self._pick_latest()
        if self._test_file:
            self._run_test()

    def _run_test(self) -> None:
        if not self._test_file:
            return
        self.test_button.setEnabled(False)
        self.test_time.setText("running …")
        self.test_output.clear()
        path, endpoint, lang = self._test_file, self.watchdog.cfg.endpoint, self.watchdog.cfg.language

        def work():
            try:
                text, secs = client.transcribe(endpoint, path, lang)
                self._bridge.done.emit(text, secs, "")
            except Exception as exc:  # noqa: BLE001
                self._bridge.done.emit("", 0.0, str(exc))

        threading.Thread(target=work, daemon=True).start()

    def _test_done(self, text: str, secs: float, error: str) -> None:
        self.test_button.setEnabled(True)
        if error:
            self.test_time.setText("Error")
            self.test_output.setPlainText(f"Error: {error}\n\nIs the server running (see »Server« page)?")
            return
        self.test_time.setText(f"{secs:.2f} s")
        self.test_output.setPlainText(text or "(no text recognized)")

    def closeEvent(self, event):  # noqa: N802 - Qt API
        event.ignore()
        self.hide()
