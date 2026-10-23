from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import tomllib



CONFIG_MAP: dict[str, tuple[str, str]] = {
    "vault_path": ("vault", "path"),
    "folder": ("vault", "folder"),
    "mic_source": ("audio", "mic_source"),
    "system_source": ("audio", "system_source"),
    "keep_audio": ("audio", "keep_audio"),
    "recordings_dir": ("audio", "recordings_dir"),
    "whisper_model": ("whisper", "model"),
    "whisper_device": ("whisper", "device"),
    "whisper_compute_type": ("whisper", "compute_type"),
    "whisper_language": ("whisper", "language"),
    "vad_filter": ("whisper", "vad_filter"),
    "llm_base_url": ("llm", "base_url"),
    "llm_api_key_env": ("llm", "api_key_env"),
    "llm_model": ("llm", "model"),
    "llm_chunk_chars": ("llm", "chunk_chars"),
}


# Audio sample rate used by capture, levels, and transcribe
SAMPLE_RATE = 16000


@dataclass
class Config:
    vault_path: str = "~/Documents/Obsidian"
    folder: str = "Meetings"
    mic_source: str = "auto"
    system_source: str = "auto"
    keep_audio: bool = False
    recordings_dir: str = "~/.local/share/meetnotes/recordings"
    whisper_model: str = "large-v3-turbo"
    whisper_device: str = "auto"
    whisper_compute_type: str = "auto"
    whisper_language: str = "auto"
    vad_filter: bool = True
    llm_base_url: str = "http://localhost:11434/v1"
    llm_api_key_env: str = "MEETNOTES_API_KEY"
    llm_model: str = "CHANGE_ME"
    llm_chunk_chars: int = 12000

    @classmethod
    def default(cls) -> "Config":
        return cls()

    @classmethod
    def load(cls, path: Path | None = None) -> "Config":
        """Load config from TOML file, falling back to defaults."""
        if path is None:
            path = Path.home() / ".config" / "meetnotes" / "config.toml"
        if not path.exists():
            return cls.default()

        try:
            with open(path, "rb") as f:
                data = tomllib.load(f)
        except tomllib.TOMLDecodeError as exc:
            raise ConfigError(f"Invalid TOML in {path}: {exc}") from exc

        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Config":
        kwargs = {}
        for field_name, default in cls.__dataclass_fields__.items():
            if field_name in CONFIG_MAP:
                section, attr = CONFIG_MAP[field_name]
                kwargs[field_name] = data.get(section, {}).get(attr, default.default)
            else:
                kwargs[field_name] = data.get(field_name, default.default)

        # Validate llm_chunk_chars
        chunk_chars = kwargs.get("llm_chunk_chars", 12000)
        if not isinstance(chunk_chars, int) or chunk_chars < 1000 or chunk_chars > 100000:
            raise ConfigError(f"llm_chunk_chars must be an integer between 1000 and 100000, got {chunk_chars}")
        kwargs["llm_chunk_chars"] = chunk_chars

        return cls(**kwargs)

    def save(self, path: Path | str) -> None:
        """Save config to TOML file, preserving any custom sections not managed by Config."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        # Read existing TOML to preserve custom sections
        existing: dict[str, dict[str, Any]] = {}
        if path.exists():
            try:
                import tomllib
                with open(path, "rb") as f:
                    existing = tomllib.load(f)
            except (tomllib.TOMLDecodeError, OSError):
                # Config file unreadable — start fresh but don't silently overwrite
                existing = {}

        # Update managed fields
        for key, value in self.__dict__.items():
            if key in CONFIG_MAP:
                section, attr = CONFIG_MAP[key]
                existing.setdefault(section, {})[attr] = value
            else:
                existing.setdefault(key, {})[key] = value

        import tomli_w
        with open(path, "wb") as f:
            tomli_w.dump(existing, f)


class ConfigError(Exception):
    pass
