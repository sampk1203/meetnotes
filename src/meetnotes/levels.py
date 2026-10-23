from __future__ import annotations

import queue
import subprocess
import threading
import time

import numpy as np

from meetnotes.config import SAMPLE_RATE


class LevelMeter:
    """Reads raw PCM from parec and emits dBFS levels via a queue.

    One instance per device. Thread-safe: worker thread reads parec stdout,
    main thread polls the queue via QTimer.
    """

    # Smoothing constants (attack/decay in seconds)
    ATTACK_TIME = 0.01  # 10 ms fast attack
    DECAY_TIME = 0.5   # 500 ms slow decay

    def __init__(self, source: str, sample_rate: int = SAMPLE_RATE, chunk_ms: int = 50):
        self.source = source
        self.sample_rate = sample_rate
        self.chunk_ms = chunk_ms
        self.chunk_frames = int(sample_rate * chunk_ms / 1000)
        self.chunk_bytes = self.chunk_frames * 2  # s16le mono

        self._queue: queue.Queue[float] = queue.Queue(maxsize=100)
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._proc: subprocess.Popen | None = None

        # Smoothing state
        self._current_db = -60.0
        self._attack_coeff = np.exp(-1.0 / (self.ATTACK_TIME * sample_rate))
        self._decay_coeff = np.exp(-1.0 / (self.DECAY_TIME * sample_rate))

    def start(self) -> None:
        """Start the parec reader thread."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop the reader thread and parec process."""
        self._stop.set()
        if self._proc is not None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                self._proc.wait()
        if self._thread is not None:
            self._thread.join(timeout=2)
        self._proc = None
        self._thread = None

    def _run(self) -> None:
        """Worker thread: read raw PCM from parec, compute dBFS, push to queue."""
        try:
            self._proc = subprocess.Popen(
                [
                    "parec",
                    "--device", self.source,
                    "--format", "s16le",
                    "--rate", str(self.sample_rate),
                    "--channels", "1",
                    "--raw",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            # parec not found — push -inf and exit
            try:
                self._queue.put_nowait(-float("inf"))
            except queue.Full:
                pass
            return

        buf = bytearray()
        while not self._stop.is_set() and self._proc is not None and self._proc.stdout is not None:
            # Read exactly chunk_bytes
            data = self._proc.stdout.read(self.chunk_bytes)
            if not data:
                break
            buf.extend(data)

            # Process complete chunks
            while len(buf) >= self.chunk_bytes:
                chunk = bytes(buf[: self.chunk_bytes])
                del buf[: self.chunk_bytes]
                db = self._pcm_to_dbfs(chunk)
                self._current_db = self._smooth(db)
                try:
                    self._queue.put_nowait(self._current_db)
                except queue.Full:
                    # Drop oldest if queue full
                    try:
                        self._queue.get_nowait()
                    except queue.Empty:
                        pass
                    try:
                        self._queue.put_nowait(self._current_db)
                    except queue.Full:
                        pass

    def _pcm_to_dbfs(self, pcm_bytes: bytes) -> float:
        """Convert s16le bytes to peak dBFS, clamped to [-60, 0]."""
        if not pcm_bytes:
            return -60.0
        # Interpret as int16
        arr = np.frombuffer(pcm_bytes, dtype=np.int16)
        if arr.size == 0:
            return -60.0
        # Peak level
        peak = np.max(np.abs(arr)) / 32768.0
        if peak <= 0:
            return -60.0
        db = 20.0 * np.log10(peak)
        return max(-60.0, min(0.0, db))

    def _smooth(self, target_db: float) -> float:
        """Apply attack/decay smoothing."""
        if target_db > self._current_db:
            # Attack (fast)
            return self._current_db + (target_db - self._current_db) * (1 - self._attack_coeff)
        else:
            # Decay (slow)
            return self._current_db + (target_db - self._current_db) * (1 - self._decay_coeff)

    def get_level(self) -> float | None:
        """Get latest dBFS level from queue. Returns None if no data."""
        try:
            return self._queue.get_nowait()
        except queue.Empty:
            return None

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()


class DualLevelMeter:
    """Manages two LevelMeters (mic + system) for the GUI."""

    def __init__(self, mic_source: str, system_source: str):
        self.mic = LevelMeter(mic_source)
        self.system = LevelMeter(system_source)
        self._no_signal_start: dict[str, float] = {}
        self._no_signal_threshold = -50.0  # dBFS floor
        self._no_signal_duration = 5.0     # seconds

    def set_sources(self, mic_source: str, system_source: str) -> None:
        """Restart meters with new device names."""
        was_running = self.mic.is_running() or self.system.is_running()
        self.mic.stop()
        self.system.stop()
        self.mic = LevelMeter(mic_source)
        self.system = LevelMeter(system_source)
        self._no_signal_start.clear()
        if was_running:
            self.start()

    def start(self) -> None:
        self.mic.start()
        self.system.start()

    def stop(self) -> None:
        self.mic.stop()
        self.system.stop()

    def get_levels(self) -> tuple[float | None, float | None]:
        """Returns (mic_db, system_db). None means no data yet."""
        return self.mic.get_level(), self.system.get_level()

    def check_no_signal(self, mic_db: float | None, sys_db: float | None) -> dict[str, str | None]:
        """Check if either source has been below threshold for too long.

        Returns dict with 'mic' and/or 'system' keys containing warning messages,
        or None if no warning.
        """
        now = time.time()
        warnings: dict[str, str | None] = {"mic": None, "system": None}

        for label, db in (("mic", mic_db), ("system", sys_db)):
            if db is not None and db > self._no_signal_threshold:
                self._no_signal_start.pop(label, None)
            elif db is not None:
                if label not in self._no_signal_start:
                    self._no_signal_start[label] = now
                elif now - self._no_signal_start[label] >= self._no_signal_duration:
                    warnings[label] = (
                        f"No signal for {self._no_signal_duration:.0f}s: "
                        f"muted or wrong device?"
                    )

        return warnings