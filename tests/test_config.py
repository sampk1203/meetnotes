"""Tests for config module."""

import tempfile
from pathlib import Path

from meetnotes.config import Config, ConfigError


def test_default_config():
    cfg = Config.default()
    assert cfg.vault_path == "~/Documents/Obsidian"
    assert cfg.folder == "Meetings"
    assert cfg.whisper_model == "large-v3-turbo"


def test_config_save_and_load():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "config.toml"
        cfg = Config.default()
        cfg.save(path)
        loaded = Config.load(path)
        assert loaded.vault_path == cfg.vault_path
        assert loaded.whisper_model == cfg.whisper_model


def test_load_fallback_to_defaults():
    """When config file missing, return defaults (not raise)."""
    cfg = Config.load(Path("/nonexistent/config.toml"))
    assert cfg.vault_path == "~/Documents/Obsidian"
