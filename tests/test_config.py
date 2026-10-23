"""Tests for config module."""

import tempfile
from pathlib import Path

import pytest

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


def test_llm_chunk_chars_validation():
    """llm_chunk_chars must be between 1000 and 100000."""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "config.toml"
        cfg = Config.default()
        cfg.llm_chunk_chars = 500  # too small
        cfg.save(path)
        with pytest.raises(ConfigError):
            Config.load(path)

    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "config.toml"
        cfg = Config.default()
        cfg.llm_chunk_chars = 200000  # too large
        cfg.save(path)
        with pytest.raises(ConfigError):
            Config.load(path)

    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "config.toml"
        cfg = Config.default()
        cfg.llm_chunk_chars = 50000  # valid
        cfg.save(path)
        loaded = Config.load(path)
        assert loaded.llm_chunk_chars == 50000
