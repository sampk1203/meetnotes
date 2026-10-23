from __future__ import annotations

import signal
import subprocess
import threading
import time
import wave
from datetime import datetime
from pathlib import Path
from typing import Any

from meetnotes.audio_devices import (
    _check_pactl,
    resolve_mic_source,
    resolve_system_source,
)
from meetnotes.config import SAMPLE_RATE


def _build_parec_args(source: str) -> list[str]:
    # --raw avoids libsndfile header-flush issues on SIGTERM; we build the WAV
    # header ourselves afterwards via stdlib wave.
    return [
        "parec",
        "--device", source,
        "--format", "s16le",
        "--rate", str(SAMPLE_RATE),
        "--channels", "1",
        "--raw",
    ]


def _pcm_to_wav(pcm_path: Path, wav_path: Path) -> None:
    """Wrap raw s16le 16kHz mono PCM into a WAV file, then delete the .pcm."""
    with wave.open(str(wav_path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)  # s16le
        wav.setframerate(SAMPLE_RATE)
        with open(pcm_path, "rb") as f:
            while chunk := f.read(8192):
                wav.writeframes(chunk)
    pcm_path.unlink()


def recover_recordings(recordings_dir: Path) -> list[Path]:
    """Find orphan .pcm files from a crashed recording and wrap them as .wav.

    Returns list of recovered wav paths (empty if none found).
    """
    if not recordings_dir.exists():
        return []
    recovered: list[Path] = []
    for pcm in recordings_dir.glob("*.pcm"):
        wav = pcm.with_suffix(".wav")
        try:
            _pcm_to_wav(pcm, wav)
            recovered.append(wav)
        except Exception:  # noqa: BLE001 — skip broken files
            pcm.unlink(missing_ok=True)
    return recovered


def start_recording(
    cfg: Any, stop_event: threading.Event | None = None
) -> tuple[Path, Path]:
    """
    Start parallel parec processes for mic and system audio.
    Writes raw PCM to .pcm files, then wraps each as .wav on exit.
    Returns (mic_path, system_path) once recording completes (SIGINT in the
    main thread, or `stop_event` being set from any thread).
    """
    _check_pactl()

    recordings_dir = Path(cfg.recordings_dir).expanduser()
    recordings_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    out_dir = recordings_dir / timestamp
    out_dir.mkdir(parents=True, exist_ok=True)

    # Recover any orphan .pcm from a crashed previous recording in this session
    recover_recordings(out_dir)

    mic_source = resolve_mic_source(cfg.mic_source)
    system_source = resolve_system_source(cfg.system_source)

    mic_pcm = out_dir / "mic.pcm"
    system_pcm = out_dir / "system.pcm"
    mic_path = out_dir / "mic.wav"
    system_path = out_dir / "system.wav"

    mic_file = open(mic_pcm, "wb")
    system_file = open(system_pcm, "wb")
    try:
        mic_proc = subprocess.Popen(_build_parec_args(mic_source), stdout=mic_file)
        system_proc = subprocess.Popen(_build_parec_args(system_source), stdout=system_file)
    except Exception:
        mic_file.close()
        system_file.close()
        raise

    pids = [mic_proc, system_proc]

    def _terminate() -> None:
        for p in pids:
            if p.poll() is None:
                p.terminate()
        for p in pids:
            p.wait(timeout=5)

    def _on_sigint(_sig: int, _frame: Any) -> None:
        _terminate()

    # signal.signal() only works in the main thread (GUI runs us in a worker).
    in_main = threading.current_thread() is threading.main_thread()
    if in_main:
        signal.signal(signal.SIGINT, _on_sigint)
    try:
        while any(p.poll() is None for p in pids):
            if stop_event is not None and stop_event.is_set():
                _terminate()
                break
            time.sleep(0.1)
    finally:
        if in_main:
            signal.signal(signal.SIGINT, signal.SIG_DFL)
        mic_file.close()
        system_file.close()
        _terminate()

    # Convert raw PCM → WAV, then delete .pcm files
    _pcm_to_wav(mic_pcm, mic_path)
    _pcm_to_wav(system_pcm, system_path)

    # Verify recordings are non-empty (check duration, not file size — WAV header is 44 bytes)
    for p in (mic_path, system_path):
        with wave.open(str(p), "rb") as w:
            if w.getnframes() == 0:
                raise RuntimeError(f"Empty recording at {p} — audio device may not be available")
    return mic_path, system_path
