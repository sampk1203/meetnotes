"""Dark-mode PyQt6 GUI for meetnotes."""

from __future__ import annotations

import atexit
import queue
import threading
from pathlib import Path
from typing import Any
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QApplication,
    QMainWindow,
    QPushButton,
    QVBoxLayout,
    QHBoxLayout,
    QWidget,
    QLabel,
    QLineEdit,
    QDialog,
    QListWidget,
    QDialogButtonBox,
    QMessageBox,
    QStyleFactory,
    QComboBox,
    QProgressBar,
    QGroupBox,
    QFormLayout,
)
from PyQt6.QtGui import QFont, QColor, QPalette


class MeetNotesGUI(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("MeetNotes")
        self.setMinimumSize(500, 480)
        self._apply_dark_theme()
        self._recording = False
        self._stopping = False
        self._processing = False
        self._stop_event = threading.Event()
        self._elapsed = 0
        self._record_timer = QTimer(self)
        self._record_timer.timeout.connect(self._tick)
        self._meter_timer = QTimer(self)
        self._meter_timer.timeout.connect(self._update_meters)
        self._result_queue: queue.Queue[str] = queue.Queue()
        self._worker_thread: threading.Thread | None = None
        self._loaders: tuple[Any, None] = (None, None)
        self._no_signal_warns: dict[str, QLabel | None] = {"mic": None, "system": None}
        self._setup_ui()
        self._start_meters()
        atexit.register(self._cleanup_at_exit)

    def _cleanup_at_exit(self) -> None:
        """Ensure any live recording is terminated when the app exits."""
        if self._recording:
            self._stop_event.set()
            if self._worker_thread is not None:
                self._worker_thread.join(timeout=5)
            from meetnotes.config import Config
            from meetnotes.capture import recover_recordings
            recover_recordings(Path(Config.load().recordings_dir))
        self._stop_meters()

    def closeEvent(self, event: Any) -> None:  # pyright: ignore[reportIncompatibleMethodOverride]
        self._cleanup_at_exit()
        event.accept()

    def _apply_dark_theme(self) -> None:
        self.setStyle(QStyleFactory.create("Fusion"))
        p = QPalette()
        dark = QColor(30, 30, 30)
        darker = QColor(25, 25, 25)
        light = QColor(220, 220, 220)
        accent = QColor(70, 130, 180)
        for role, color in [
            (QPalette.ColorRole.Window, dark),
            (QPalette.ColorRole.WindowText, light),
            (QPalette.ColorRole.Base, darker),
            (QPalette.ColorRole.AlternateBase, dark),
            (QPalette.ColorRole.ToolTipBase, dark),
            (QPalette.ColorRole.ToolTipText, light),
            (QPalette.ColorRole.Text, light),
            (QPalette.ColorRole.Button, dark),
            (QPalette.ColorRole.ButtonText, light),
            (QPalette.ColorRole.BrightText, QColor(255, 255, 255)),
            (QPalette.ColorRole.Link, accent),
            (QPalette.ColorRole.Highlight, accent),
            (QPalette.ColorRole.HighlightedText, QColor(20, 20, 20)),
        ]:
            p.setColor(role, color)
        self.setPalette(p)

    def _setup_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        lay = QVBoxLayout(central)
        lay.setSpacing(12)
        lay.setContentsMargins(20, 20, 20, 20)

        # Title
        lbl = QLabel("MeetNotes")
        lbl.setFont(QFont("Segoe UI", 18, QFont.Weight.Bold))
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(lbl)

        # Status + Timer row
        status_row = QHBoxLayout()
        self._status_lbl = QLabel("Ready")
        self._status_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._timer_lbl = QLabel("00:00")
        self._timer_lbl.setFont(QFont("Courier New", 24))
        self._timer_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        status_row.addWidget(self._status_lbl)
        status_row.addWidget(self._timer_lbl)
        lay.addLayout(status_row)

        # Device selection group
        dev_group = QGroupBox("Audio Sources")
        dev_lay = QFormLayout(dev_group)
        dev_lay.setFormAlignment(Qt.AlignmentFlag.AlignCenter)
        dev_lay.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        dev_lay.setSpacing(8)

        self._mic_combo = QComboBox()
        self._mic_combo.setMinimumWidth(250)
        self._mic_combo.currentIndexChanged.connect(self._on_mic_changed)
        dev_lay.addRow("Microphone:", self._mic_combo)

        self._mic_bar = QProgressBar()
        self._mic_bar.setRange(-60, 0)
        self._mic_bar.setValue(-60)
        self._mic_bar.setTextVisible(False)
        self._mic_db_lbl = QLabel("-60 dB")
        self._mic_lvl_row = QHBoxLayout()
        self._mic_lvl_row.addWidget(self._mic_bar)
        self._mic_lvl_row.addWidget(self._mic_db_lbl)
        self._no_signal_warns["mic"] = QLabel()
        self._no_signal_warns["mic"].setObjectName("warn")
        self._no_signal_warns["mic"].setStyleSheet("color: #f44336; font-size: 11px;")
        dev_lay.addRow("", self._mic_lvl_row)
        dev_lay.addRow("", self._no_signal_warns["mic"])

        self._sys_combo = QComboBox()
        self._sys_combo.setMinimumWidth(250)
        self._sys_combo.currentIndexChanged.connect(self._on_sys_changed)
        dev_lay.addRow("System audio:", self._sys_combo)

        self._sys_bar = QProgressBar()
        self._sys_bar.setRange(-60, 0)
        self._sys_bar.setValue(-60)
        self._sys_bar.setTextVisible(False)
        self._sys_db_lbl = QLabel("-60 dB")
        self._sys_lvl_row = QHBoxLayout()
        self._sys_lvl_row.addWidget(self._sys_bar)
        self._sys_lvl_row.addWidget(self._sys_db_lbl)
        self._no_signal_warns["system"] = QLabel()
        self._no_signal_warns["system"].setObjectName("warn")
        self._no_signal_warns["system"].setStyleSheet("color: #f44336; font-size: 11px;")
        dev_lay.addRow("", self._sys_lvl_row)
        dev_lay.addRow("", self._no_signal_warns["system"])

        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self._refresh_sources)
        dev_lay.addRow("", refresh_btn)
        lay.addWidget(dev_group)

        # Record button
        self._record_btn = QPushButton("Record")
        self._record_btn.clicked.connect(self._toggle)
        self._record_btn.setMinimumHeight(40)
        lay.addWidget(self._record_btn)

        # Title input
        tl = QLabel("Title (optional):")
        lay.addWidget(tl)
        self._title_input = QLineEdit()
        self._title_input.setPlaceholderText("Auto-generated if empty")
        lay.addWidget(self._title_input)

        # Action buttons
        btn_row = QHBoxLayout()
        self._process_btn = QPushButton("Process last recording")
        self._process_btn.clicked.connect(self._process_last)
        open_btn = QPushButton("Open recordings folder")
        open_btn.clicked.connect(self._open_folder)
        btn_row.addWidget(self._process_btn)
        btn_row.addWidget(open_btn)
        lay.addLayout(btn_row)

        settings_btn = QPushButton("Settings")
        settings_btn.clicked.connect(self._show_settings)
        lay.addWidget(settings_btn)

        self._load_devices()

    def _load_devices(self) -> None:
        """Populate dropdowns from current config or defaults."""
        from meetnotes.config import Config
        from meetnotes.audio_devices import get_input_devices, get_monitor_devices
        cfg = Config.load()
        self._cfg = cfg  # Store for save later
        try:
            inputs = get_input_devices()
        except FileNotFoundError:
            inputs = []
            QMessageBox.warning(self, "No audio", "pulseaudio-utils not found — cannot detect audio devices.")
        except RuntimeError as exc:
            inputs = []
            QMessageBox.warning(self, "No audio", str(exc))
        try:
            monitors = get_monitor_devices()
        except (FileNotFoundError, RuntimeError):
            monitors = []
        self._mic_combo.clear()
        self._sys_combo.clear()
        for d in inputs:
            desc = f"{d['description']} ({d['name']})"
            self._mic_combo.addItem(desc, d["name"])
            if cfg.mic_source and cfg.mic_source == d["name"]:
                self._mic_combo.setCurrentIndex(self._mic_combo.count() - 1)
        if inputs and not any(cfg.mic_source == d["name"] for d in inputs):
            # Default: first or auto
            auto_mic = next((d["name"] for d in inputs if d.get("is_default")), inputs[0]["name"] if inputs else None)
            if auto_mic:
                for i in range(self._mic_combo.count()):
                    if self._mic_combo.itemData(i) == auto_mic:
                        self._mic_combo.setCurrentIndex(i)
                        break
        for d in monitors:
            desc = f"{d['description']} ({d['name']})"
            self._sys_combo.addItem(desc, d["name"])
            if cfg.system_source and cfg.system_source == d["name"]:
                self._sys_combo.setCurrentIndex(self._sys_combo.count() - 1)
        if monitors and not any(cfg.system_source == d["name"] for d in monitors):
            auto_sys = next((d["name"] for d in monitors if d.get("is_default")), monitors[0]["name"] if monitors else None)
            if auto_sys:
                for i in range(self._sys_combo.count()):
                    if self._sys_combo.itemData(i) == auto_sys:
                        self._sys_combo.setCurrentIndex(i)
                        break

    def _refresh_sources(self) -> None:
        self._load_devices()
        self._stop_meters()
        self._start_meters()

    def _on_mic_changed(self, _index: int) -> None:  # pyright: ignore[reportUnusedParameter]
        self._save_device_selection()
        self._stop_meters()
        self._start_meters()

    def _on_sys_changed(self, _index: int) -> None:  # pyright: ignore[reportUnusedParameter]
        self._save_device_selection()
        self._stop_meters()
        self._start_meters()

    def _save_device_selection(self) -> None:
        from meetnotes.config import Config
        import tomli_w
        # Use cached config from _load_devices if available to avoid double-read
        cfg = self._cfg if hasattr(self, "_cfg") else Config.load()
        cfg.mic_source = self._mic_combo.currentData() or cfg.mic_source
        cfg.system_source = self._sys_combo.currentData() or cfg.system_source
        cfg_path = Path.home() / ".config" / "meetnotes" / "config.toml"
        data: dict = {}
        if cfg_path.exists():
            with open(cfg_path, "rb") as f:
                import tomllib
                data = tomllib.load(f)
        data.setdefault("audio", {})
        data["audio"]["mic_source"] = cfg.mic_source
        data["audio"]["system_source"] = cfg.system_source
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        with open(cfg_path, "wb") as f:
            tomli_w.dump(data, f)

    def _start_meters(self) -> None:
        from meetnotes.levels import DualLevelMeter
        mic_source = self._mic_combo.currentData() or "auto"
        sys_source = self._sys_combo.currentData() or "auto"
        self._loaders = (
            DualLevelMeter(mic_source, sys_source),
            None,
        )
        self._meter_timer.start(100)  # ~10 Hz update

    def _stop_meters(self) -> None:
        self._meter_timer.stop()
        if self._loaders[0]:
            self._loaders[0].stop()
            self._loaders = (None, None)

    def _update_meters(self) -> None:
        meters = self._loaders[0]
        if not meters:
            return
        mic_db, sys_db = meters.get_levels()
        self._update_bar(self._mic_bar, self._mic_db_lbl, mic_db)
        self._update_bar(self._sys_bar, self._sys_db_lbl, sys_db)
        warns = meters.check_no_signal(mic_db, sys_db)
        for key, lbl in self._no_signal_warns.items():
            if lbl is not None:
                lbl.setText(warns.get(key) or "")

    def _update_bar(self, bar: QProgressBar, db_lbl: QLabel, db: float | None) -> None:
        if db is None:
            bar.setValue(-60)
            db_lbl.setText("-60 dB")
        else:
            clamped = max(-60.0, min(0.0, db))
            bar.setValue(int(clamped))
            db_lbl.setText(f"{clamped:.0f} dB")

    def _toggle(self) -> None:
        if not self._recording:
            self._start()
        else:
            self._stop()

    def _start(self) -> None:
        self._recording = True
        self._stopping = False
        self._processing = False
        self._stop_event.clear()
        self._elapsed = 0
        self._record_timer.start(1000)
        self._record_btn.setText("Stop")
        self._process_btn.setEnabled(False)
        self._status_lbl.setText("Recording...")
        self._tick()
        t = threading.Thread(target=self._run, daemon=True)
        t.start()
        self._worker_thread = t

    def _run(self) -> None:
        from meetnotes.config import Config
        from meetnotes.capture import start_recording
        from meetnotes.pipeline import run_pipeline
        cfg = Config.load()
        try:
            mic, system = start_recording(cfg, self._stop_event)
            result = run_pipeline(mic, system, cfg, self._title_input.text() or None, no_llm=False)
            self._result_queue.put(f"Done: {result['note_path'].name}")
        except (Exception, KeyboardInterrupt) as exc:
            self._result_queue.put(f"Error: {exc}")

    def _tick(self) -> None:
        if not self._recording and not self._processing:
            return
        try:
            while True:
                msg = self._result_queue.get_nowait()
                self._record_timer.stop()
                self._meter_timer.stop()
                self._recording = False
                self._stopping = False
                self._processing = False
                self._record_btn.setText("Record")
                self._record_btn.setEnabled(True)
                self._process_btn.setEnabled(True)
                self._status_lbl.setText(msg)
                return
        except queue.Empty:
            pass
        if self._stopping:
            return
        self._elapsed += 1
        m, s = divmod(self._elapsed, 60)
        self._timer_lbl.setText(f"{m:02d}:{s:02d}")

    def _stop(self) -> None:
        self._stopping = True
        self._stop_event.set()
        self._record_btn.setEnabled(False)
        self._status_lbl.setText("Stopping...")

    def _process_last(self) -> None:
        from meetnotes.config import Config
        from meetnotes.recordings import last_recording
        from meetnotes.capture import recover_recordings
        cfg = Config.load()
        rec_dir = Path(cfg.recordings_dir).expanduser()
        last = last_recording(rec_dir)
        if last is None:
            recover_recordings(rec_dir)
            last = last_recording(rec_dir)
        if last is None:
            QMessageBox.warning(self, "No recording", "No recordings found.")
            return
        mic = last["path"] / "mic.wav"
        sys_w = last["path"] / "system.wav"
        self._status_lbl.setText(f"Processing: {last['name']}...")
        self._processing = True
        self._record_btn.setEnabled(False)
        self._process_btn.setEnabled(False)
        threading.Thread(target=self._run_pipeline, args=(mic, sys_w, cfg), daemon=True).start()

    def _run_pipeline(self, mic: Path, sys_w: Path, cfg) -> None:
        from meetnotes.pipeline import run_pipeline
        try:
            result = run_pipeline(mic, sys_w, cfg, self._title_input.text() or None, no_llm=False)
            self._result_queue.put(f"Done: {result['note_path'].name}")
        except Exception as exc:
            self._result_queue.put(f"Error: {exc}")

    def _open_folder(self) -> None:
        from meetnotes.config import Config
        rec_dir = Path(Config.load().recordings_dir).expanduser()
        rec_dir.mkdir(parents=True, exist_ok=True)
        import subprocess
        subprocess.Popen(["xdg-open", str(rec_dir)])

    def _show_sources(self) -> None:
        from meetnotes.capture import list_sources
        dialog = QDialog(self)
        dialog.setWindowTitle("Audio Sources")
        dialog.setMinimumWidth(500)
        lay = QVBoxLayout(dialog)
        lw = QListWidget()
        for src in list_sources():
            auto = " [AUTO]" if src.get("auto") else ""
            lw.addItem(f"{src['name']}{auto}\n   {src.get('description', '')}")
        lay.addWidget(lw)
        btn = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        btn.accepted.connect(dialog.accept)
        lay.addWidget(btn)
        dialog.exec()

    def _show_settings(self) -> None:
        cfg_path = Path.home() / ".config" / "meetnotes" / "config.toml"
        QMessageBox.information(
            self, "Settings",
            f"Config file: {cfg_path}\n\nEdit directly with your editor.",
        )


def run_gui() -> None:
    app = QApplication.instance() or QApplication([])
    w = MeetNotesGUI()
    w.show()
    app.exec()


if __name__ == "__main__":
    run_gui()