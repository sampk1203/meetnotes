"""Recordings management module."""

from __future__ import annotations

import wave
from datetime import datetime
from pathlib import Path
from typing import Any


def scan_recordings(recordings_dir: Path) -> list[dict[str, Any]]:
    """Scan recordings directory and return list of recording info dicts.

    Each dict has keys: path, name, timestamp, has_mic, has_system, duration, size, status.
    Status: 'ok' | 'recoverable' | 'empty'
    """
    if not recordings_dir.exists():
        return []

    recordings = []
    for folder in sorted(recordings_dir.iterdir(), reverse=True):
        if not folder.is_dir():
            continue
        name = folder.name
        try:
            ts = datetime.strptime(name, "%Y-%m-%d_%H%M")
        except ValueError:
            ts = datetime.min

        mic = folder / "mic.wav"
        sys_w = folder / "system.wav"
        has_mic = mic.exists()
        has_system = sys_w.exists()

        # Check for recoverable .pcm files
        pcms = list(folder.glob("*.pcm"))
        is_recoverable = not (has_mic and has_system) and len(pcms) > 0

        # Calculate duration and size
        duration = 0.0
        size = 0
        status = "empty"
        if has_mic and has_system:
            status = "ok"
            if has_mic:
                try:
                    with wave.open(str(mic), "rb") as w:
                        duration += w.getnframes() / w.getframerate()
                except Exception:
                    pass
            if has_system:
                try:
                    with wave.open(str(sys_w), "rb") as w:
                        duration += w.getnframes() / w.getframerate()
                except Exception:
                    pass
            size = (mic.stat().st_size if has_mic else 0) + (sys_w.stat().st_size if has_system else 0)
        elif is_recoverable:
            status = "recoverable"
            # Size of .pcm files
            size = sum(p.stat().st_size for p in pcms)

        recordings.append({
            "path": folder,
            "name": name,
            "timestamp": ts,
            "has_mic": has_mic,
            "has_system": has_system,
            "duration": duration,
            "size": size,
            "status": status,
            "is_recoverable": is_recoverable,
        })
    return recordings


def last_recording(recordings_dir: Path) -> dict[str, Any] | None:
    """Get the most recent complete recording."""
    recordings = scan_recordings(recordings_dir)
    for rec in recordings:
        if rec["status"] == "ok":
            return rec
    return None


def safe_delete(recording: dict[str, Any], recordings_dir: Path) -> bool:
    """Safely delete a recording folder.

    Returns True if deleted, False if refused (path outside recordings_dir).
    Refuses symlink escapes and non-recording files.
    """
    folder = recording["path"]

    # Resolve paths to prevent symlink escapes
    recordings_resolved = recordings_dir.resolve()
    try:
        folder_resolved = folder.resolve()
    except (OSError, RuntimeError):
        return False

    # Must be a direct child of recordings_dir
    if not folder_resolved.is_relative_to(recordings_resolved):
        return False

    # Delete only known files
    known_files = ["mic.wav", "system.wav"]
    for f in known_files:
        p = folder / f
        if p.exists():
            p.unlink()

    # Delete any leftover .pcm files
    for p in folder.glob("*.pcm"):
        p.unlink()

    # Remove empty folder
    try:
        folder.rmdir()
    except OSError:
        # Folder not empty (has other files)
        pass

    return True


def get_recording_size(recording: dict[str, Any]) -> float:
    """Get recording size in MB for display."""
    return recording["size"] / (1024 * 1024)


def format_duration(seconds: float) -> str:
    """Format duration as M:SS or HH:MM:SS."""
    if seconds < 60:
        return f"{int(seconds)}s"
    minutes, secs = divmod(int(seconds), 60)
    if minutes < 60:
        return f"{minutes}:{secs:02d}"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}"
