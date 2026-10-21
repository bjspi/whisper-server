"""Benchmark panel on the model page: record or pick audio, then time every downloaded model one by one."""

from __future__ import annotations

import json
import shutil
import sys
import threading
import time
import wave
from pathlib import Path

from PyQt6.QtCore import QProcess, QProcessEnvironment, Qt, QTimer
from PyQt6.QtWidgets import (
    QAbstractItemView, QComboBox, QFileDialog, QHeaderView, QLabel, QPlainTextEdit, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from whisperserver.bench import REFERENCE_WAV
from whisperserver.process import child_environment
from whisperserver.ui.rows import COMBO_WIDTH, Card, card_title, controls

SR = 16000
SOURCES = (("reference", "Reference recording"), ("recording", "New recording"),
           ("whispertyper", "Last WhisperTyper recording"), ("file", "Choose file …"))


def wav_seconds(path: Path) -> float | None:
    try:
        with wave.open(str(path)) as w:
            return w.getnframes() / float(w.getframerate())
    except (wave.Error, OSError, EOFError):
        return None


class Recorder:
    """16 kHz mono microphone recording via sounddevice (PortAudio)."""

    def __init__(self):
        self._chunks: list = []
        self._stream = None
        self._lock = threading.Lock()
        self.started = 0.0

    @property
    def active(self) -> bool:
        return self._stream is not None

    def start(self) -> None:
        import sounddevice as sd

        self._chunks = []

        def callback(indata, frames, t, status):  # noqa: ARG001 - PortAudio signature
            with self._lock:
                self._chunks.append(indata.copy())

        self._stream = sd.InputStream(samplerate=SR, channels=1, dtype="int16", callback=callback)
        self._stream.start()
        self.started = time.monotonic()

    def stop(self, target: Path) -> float:
        import numpy as np

        stream, self._stream = self._stream, None
        if stream is not None:
            stream.stop()
            stream.close()
        with self._lock:
            audio = np.concatenate(self._chunks) if self._chunks else np.zeros((0, 1), dtype=np.int16)
        target.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(target), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SR)
            w.writeframes(audio.tobytes())
        return len(audio) / SR


class BenchmarkPanel(QWidget):
    def __init__(self, settings_window):
        super().__init__()
        self.win = settings_window
        self.recorder = Recorder()
        self.recording_path = settings_window.watchdog.cfg.data_dir / "benchmark_recording.wav"
        self.custom_file: Path | None = None
        self.proc: QProcess | None = None
        self._buffer = ""
        self._texts: dict[int, str] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(card_title("Benchmark"))
        card = Card()
        self.source = QComboBox()
        self.source.setFixedWidth(COMBO_WIDTH)
        for key, label in SOURCES:
            self.source.addItem(label, key)
        self.source.currentIndexChanged.connect(self._source_changed)
        self.source_row = card.row("Audio", "", self.source)

        self.record_button = QPushButton("●  Record")
        self.record_button.clicked.connect(self._toggle_record)
        self.reference_button = QPushButton("Save as reference")
        self.reference_button.clicked.connect(self._save_reference)
        self.record_row = card.row("Microphone", "Speak normally for about 15 s, then stop.",
                                   controls(self.reference_button, self.record_button))
        self.run_button = QPushButton("Run benchmark")
        self.run_button.setObjectName("primary")
        self.run_button.clicked.connect(self._run)
        self.run_row = card.row("Benchmark all models", "Loads every downloaded model one after another on the "
                                "selected device and transcribes 3×. The live server keeps running.",
                                self.run_button)
        layout.addWidget(card)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Model", "Load", "1st run", "Best", "Real-time"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setShowGrid(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col in range(1, 5):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setMinimumHeight(150)
        self.table.itemSelectionChanged.connect(self._show_text)
        layout.addSpacing(10)
        layout.addWidget(self.table)
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setFixedHeight(90)
        self.text.setPlaceholderText("Select a row to see the recognized text.")
        layout.addSpacing(8)
        layout.addWidget(self.text)

        self.timer = QTimer(self)
        self.timer.setInterval(200)
        self.timer.timeout.connect(self._tick)
        self._source_changed()

    # --- source
    def _key(self) -> str:
        return self.source.currentData()

    def audio_path(self) -> Path | None:
        key = self._key()
        if key == "reference":
            return REFERENCE_WAV if REFERENCE_WAV.is_file() else None
        if key == "recording":
            return self.recording_path if self.recording_path.is_file() else None
        if key == "whispertyper":
            from whisperserver.ui.settings import latest_whispertyper_recording
            return latest_whispertyper_recording()
        return self.custom_file

    def _source_changed(self) -> None:
        key = self._key()
        if key == "file" and self.sender() is self.source:
            name, _ = QFileDialog.getOpenFileName(self, "Choose audio file", "",
                                                  "Audio (*.wav *.mp3 *.m4a *.ogg *.flac *.webm);;All files (*)")
            if name:
                self.custom_file = Path(name)
        self.record_row.setVisible(key == "recording")
        self._update_source_text()

    def _update_source_text(self) -> None:
        path = self.audio_path()
        if path is None:
            hint = {"recording": "No recording yet - record one below.",
                    "whispertyper": "No WhisperTyper recording found in %TEMP%.",
                    "reference": "No reference recording yet - record one first."}.get(self._key(), "No file chosen.")
        else:
            secs = wav_seconds(path)
            hint = path.name + (f"  ·  {secs:.1f} s" if secs else "")
        self.source_row.description.setText(hint)
        self.source_row.description.setVisible(True)
        self.reference_button.setEnabled(self.recording_path.is_file() and not self.recorder.active)
        self.run_button.setEnabled(path is not None and self.proc is None and not self.recorder.active)

    # --- recording
    def _toggle_record(self) -> None:
        if not self.recorder.active:
            try:
                self.recorder.start()
            except Exception as exc:  # noqa: BLE001 - no microphone, device busy ...
                self.record_row.description.setText(f"Microphone not available: {exc}")
                return
            self.record_button.setText("■  Stop")
            self.timer.start()
        else:
            self.timer.stop()
            secs = self.recorder.stop(self.recording_path)
            self.record_button.setText("●  Record again")
            self.record_row.description.setText(f"Recorded: {secs:.1f} s")
        self._update_source_text()

    def _tick(self) -> None:
        self.record_row.description.setText(f"Recording …  {time.monotonic() - self.recorder.started:.1f} s")

    def _save_reference(self) -> None:
        if self.recording_path.is_file():
            REFERENCE_WAV.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(self.recording_path, REFERENCE_WAV)
            self.record_row.description.setText("Saved as reference recording.")

    # --- benchmark process
    def _run(self) -> None:
        path = self.audio_path()
        if path is None or self.proc is not None:
            return
        self.table.setRowCount(0)
        self._texts.clear()
        self.text.clear()
        device = self.win.device_combo.currentData()
        exe = Path(sys.executable)
        self.proc = QProcess(self)
        env = QProcessEnvironment()
        for k, v in child_environment().items():
            env.insert(k, v)
        self.proc.setProcessEnvironment(env)
        self.proc.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
        self.proc.readyReadStandardOutput.connect(self._read)
        self.proc.finished.connect(self._finished)
        python = exe.with_name("python.exe") if exe.with_name("python.exe").is_file() else exe
        self.proc.start(str(python), ["-m", "whisperserver.bench", str(path), "--device", device, "--runs", "3"])
        self.run_button.setEnabled(False)
        self.run_button.setText("Running …")
        self.run_row.description.setText(f"Starting benchmark on {device} …")

    def _read(self) -> None:
        self._buffer += bytes(self.proc.readAllStandardOutput()).decode("utf-8", "replace")
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            try:
                self._event(json.loads(line))
            except json.JSONDecodeError:
                continue

    def _row(self, label: str, *cells: str) -> int:
        row = self.table.rowCount()
        self.table.insertRow(row)
        for col, value in enumerate((label, *cells)):
            item = QTableWidgetItem(value)
            if col:
                item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(row, col, item)
        return row

    def _event(self, ev: dict) -> None:
        kind = ev.get("event")
        label = ev.get("label", "")
        if kind == "start":
            self.run_row.description.setText(f"{ev['models']} models · {ev['audio_s']:.1f} s audio · {ev['device']}")
        elif kind == "loading":
            self.run_row.description.setText(f"Loading {label} …")
        elif kind == "result":
            row = self._row(label, f"{ev['load_s']:.1f} s", f"{ev['first_s']:.2f} s", f"{ev['best_s']:.2f} s",
                            f"{1 / ev['rtf']:.0f}×" if ev.get("rtf") else "-")
            self._texts[row] = ev.get("text", "")
        elif kind == "skipped":
            self._row(label, "-", "-", "-", "missing")
        elif kind == "error":
            row = self._row(label, "Error", "", "", "")
            self._texts[row] = ev.get("error", "")

    def _show_text(self) -> None:
        rows = self.table.selectionModel().selectedRows()
        self.text.setPlainText(self._texts.get(rows[0].row(), "") if rows else "")

    def _finished(self, code: int, _status) -> None:
        self._read()
        err = bytes(self.proc.readAllStandardError()).decode("utf-8", "replace").strip()
        self.proc = None
        self.run_button.setText("Run benchmark")
        if code != 0:
            self.run_row.description.setText("Benchmark aborted: " + (err.splitlines()[-1] if err else f"code {code}"))
        else:
            self.run_row.description.setText(self.run_row.description.text().split(" · Done")[0] + " · Done. "
                                             "Real-time = how much faster than the speaking time.")
        if self.table.rowCount():
            self.table.selectRow(0)
        self._update_source_text()

    def shutdown(self) -> None:
        if self.recorder.active:
            self.recorder.stop(self.recording_path)
        if self.proc is not None:
            self.proc.kill()
