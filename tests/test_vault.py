"""Tests for vault module."""

import tempfile
from pathlib import Path

import pytest

from meetnotes.config import Config
from meetnotes.vault import write_note, _sanitize_title, _find_unique_path


def test_sanitize_title():
    assert _sanitize_title("Hello World!") == "Hello World"
    assert _sanitize_title("Test/File") == "TestFile"
    assert _sanitize_title("  spaces  ") == "spaces"


def test_find_unique_path():
    with tempfile.TemporaryDirectory() as tmpdir:
        base = Path(tmpdir) / "test.md"
        base.touch()
        unique = _find_unique_path(base)
        assert unique.name == "test_1.md"


def test_write_note():
    with tempfile.TemporaryDirectory() as tmpdir:
        cfg = Config.default()
        cfg.vault_path = tmpdir
        cfg.folder = "Meetings"
        result = write_note(cfg, "Test Meeting", {
            "segments": [],
            "summary": "# Test",
            "duration": 0.0,
        })
        assert result["note_path"].exists()
        assert result["transcript_path"].exists()
        assert "Test Meeting" in result["note_path"].name
