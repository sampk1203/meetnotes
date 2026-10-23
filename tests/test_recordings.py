"""Tests for recordings module."""

import os
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from meetnotes.recordings import (
    scan_recordings,
    last_recording,
    safe_delete,
    get_recording_size,
    format_duration,
)


def test_scan_recordings_empty(tmp_path):
    """scan_recordings returns empty list when dir doesn't exist."""
    assert scan_recordings(tmp_path / "nonexistent") == []


def test_scan_recordings_finds_ok_recordings(tmp_path):
    """scan_recordings finds valid recordings with .wav files."""
    rec_dir = tmp_path / "recordings"
    rec_dir.mkdir()

    # Create a valid recording folder
    folder = rec_dir / "2024-01-15_1430"
    folder.mkdir()
    (folder / "mic.wav").write_bytes(b"\x00\x00" * 100)
    (folder / "system.wav").write_bytes(b"\x00\x00" * 100)

    recordings = scan_recordings(rec_dir)
    assert len(recordings) == 1
    assert recordings[0]["status"] == "ok"
    assert recordings[0]["has_mic"] is True
    assert recordings[0]["has_system"] is True
    assert recordings[0]["size"] > 0


def test_scan_recordings_finds_recoverable(tmp_path):
    """scan_recordings identifies recoverable recordings (.pcm without .wav)."""
    rec_dir = tmp_path / "recordings"
    rec_dir.mkdir()

    folder = rec_dir / "2024-01-15_1430"
    folder.mkdir()
    (folder / "mic.pcm").write_bytes(b"\x00\x00" * 100)
    (folder / "system.pcm").write_bytes(b"\x00\x00" * 100)

    recordings = scan_recordings(rec_dir)
    assert len(recordings) == 1
    assert recordings[0]["status"] == "recoverable"
    assert recordings[0]["is_recoverable"] is True


def test_last_recording_returns_latest(tmp_path):
    """last_recording returns the most recent ok recording."""
    rec_dir = tmp_path / "recordings"
    rec_dir.mkdir()

    # Create two recordings
    for name in ["2024-01-15_1430", "2024-01-16_1000"]:
        folder = rec_dir / name
        folder.mkdir()
        (folder / "mic.wav").write_bytes(b"\x00\x00" * 100)
        (folder / "system.wav").write_bytes(b"\x00\x00" * 100)

    rec = last_recording(rec_dir)
    assert rec is not None
    assert rec["name"] == "2024-01-16_1000"


def test_last_recording_skips_empty(tmp_path):
    """last_recording skips empty/incomplete recordings."""
    rec_dir = tmp_path / "recordings"
    rec_dir.mkdir()

    # Only have an incomplete recording
    folder = rec_dir / "2024-01-15_1430"
    folder.mkdir()
    (folder / "mic.wav").write_bytes(b"\x00\x00" * 100)

    assert last_recording(rec_dir) is None


def test_safe_delete_rejects_path_outside(tmp_path):
    """safe_delete refuses paths outside recordings_dir."""
    rec_dir = tmp_path / "recordings"
    rec_dir.mkdir()
    fake_rec = {"path": Path("/tmp/other/folder")}

    result = safe_delete(fake_rec, rec_dir)
    assert result is False


def test_safe_delete_deletes_known_files():
    """safe_delete removes mic.wav and system.wav."""
    rec_dir = Path("/tmp/test-recordings")
    folder = Path("/tmp/test-recordings/rec1")

    # Mock the folder and its files
    mock_folder = MagicMock()
    mock_folder.__truediv__ = lambda self, name: Path(folder / name)
    mock_folder.iterdir = lambda: []
    mock_folder.exists = lambda: True
    mock_folder.resolve = lambda: Path("/tmp/test-recordings/rec1")

    rec = {"path": mock_folder}

    deleted = []
    def mock_unlink(*args, **kwargs):
        deleted.append(True)

    with patch("pathlib.Path.exists", return_value=True), \
         patch("pathlib.Path.unlink", mock_unlink), \
         patch("pathlib.Path.rmdir", MagicMock()):
        result = safe_delete(rec, rec_dir)

    assert result is True
    assert len(deleted) >= 2  # At least mic.wav and system.wav


def test_get_recording_size(tmp_path):
    """get_recording_size returns size in MB."""
    rec = {"size": 1024 * 1024 * 5}  # 5 MB
    assert get_recording_size(rec) == 5.0


def test_format_duration_short():
    """format_duration handles short durations."""
    assert format_duration(30) == "30s"
    assert format_duration(45.5) == "45s"


def test_format_duration_minutes():
    """format_duration handles minute-level durations."""
    assert format_duration(90) == "1:30"
    assert format_duration(120) == "2:00"


def test_format_duration_hours():
    """format_duration handles hour-level durations."""
    assert format_duration(3600) == "1:00:00"
    assert format_duration(7261) == "2:01:01"
