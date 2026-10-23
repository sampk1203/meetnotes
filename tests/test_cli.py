"""Tests for CLI module."""

import argparse
import tempfile
from pathlib import Path
from unittest.mock import patch

from meetnotes.cli import main
from meetnotes.config import Config


def test_init_creates_config():
    with tempfile.TemporaryDirectory() as tmpdir:
        config_path = Path(tmpdir) / ".config" / "meetnotes" / "config.toml"
        with patch("pathlib.Path.home", return_value=Path(tmpdir)):
            result = main(["init"])
        assert result == 0
        assert config_path.exists()


def test_init_skips_existing():
    with tempfile.TemporaryDirectory() as tmpdir:
        config_path = Path(tmpdir) / ".config" / "meetnotes" / "config.toml"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text("[vault]\npath = 'x'\n")
        with patch("pathlib.Path.home", return_value=Path(tmpdir)):
            result = main(["init"])
        assert result == 2


def test_sources_requires_pactl():
    """sources command fails when pactl is missing."""
    with patch("meetnotes.audio_devices.shutil.which", return_value=None):
        result = main(["sources"])
    assert result == 2
