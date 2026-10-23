from __future__ import annotations

import json
import shutil
import subprocess
from typing import Any


def _check_pactl() -> None:
    """Raise FileNotFoundError if pactl is not installed."""
    if not shutil.which("pactl"):
        raise FileNotFoundError("pactl not found — install pulseaudio-utils")


def _get_sources_json() -> list[dict[str, Any]] | None:
    """Try to get sources via pactl --format=json. Returns None if unsupported."""
    try:
        output = subprocess.check_output(
            ["pactl", "--format=json", "list", "sources"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
        return json.loads(output)
    except (subprocess.CalledProcessError, json.JSONDecodeError, FileNotFoundError):
        return None


def _get_sources_short() -> list[dict[str, Any]]:
    """Fallback: parse pactl list short sources (no description/state/mute)."""
    output = subprocess.check_output(
        ["pactl", "list", "short", "sources"], text=True, stderr=subprocess.DEVNULL
    )
    sources = []
    for line in output.strip().splitlines():
        parts = line.split()
        if len(parts) < 3:
            continue
        name = parts[1]
        # Guess kind from name suffix
        kind = "monitor" if name.endswith(".monitor") else "input"
        desc = name
        sources.append(
            {
                "name": name,
                "description": desc,
                "kind": kind,
                "state": "UNKNOWN",
                "muted": False,
                "volume": 0,
                "is_default": False,
                "index": int(parts[0]),
            }
        )
    return sources


def get_default_source() -> str | None:
    """Get the default source name."""
    try:
        return subprocess.check_output(
            ["pactl", "get-default-source"], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except subprocess.CalledProcessError:
        return None


def get_default_sink() -> str | None:
    """Get the default sink name."""
    try:
        return subprocess.check_output(
            ["pactl", "get-default-sink"], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except subprocess.CalledProcessError:
        return None


def parse_sources(
    raw: list[dict[str, Any]], default_source: str | None, default_sink: str | None
) -> list[dict[str, Any]]:
    """Parse raw pactl JSON into our canonical device dict."""
    devices: list[dict[str, Any]] = []
    for src in raw:
        props = src.get("properties", {})
        name = src.get("name", "")
        if not name:
            continue

        # Determine kind from name suffix or device.class
        kind = "monitor" if name.endswith(".monitor") else "input"
        # Prefer device.class if present (e.g., "monitor" vs "source")
        if "device.class" in props:
            kind = "monitor" if props["device.class"] == "monitor" else "input"

        description = (
            props.get("device.description")
            or props.get("alsa.card_name")
            or props.get("node.description")
            or name
        )

        # State: RUNNING, IDLE, SUSPENDED
        state = src.get("state", "UNKNOWN")

        # Mute and volume
        mute = src.get("mute", False)
        volume = 0
        if "volume" in src:
            vals = src["volume"].get("values", [])
            if vals:
                volume = vals[0]

        # An input device is "auto" if it's the default source; a monitor is "auto"
        # if its base sink is the default sink (i.e., name == default_sink + ".monitor").
        expected_auto_input = name == default_source
        expected_auto_monitor = default_sink is not None and name == f"{default_sink}.monitor"
        is_default = (kind == "input" and expected_auto_input) or (
            kind == "monitor" and expected_auto_monitor
        )
        devices.append(
            {
                "name": name,
                "description": description,
                "kind": kind,
                "state": state,
                "muted": mute,
                "volume": volume,
                "is_default": is_default,
                "index": src.get("index", 0),
            }
        )
    return devices


def get_audio_devices() -> list[dict[str, Any]]:
    """Return all audio sources with kind, state, mute, and description."""
    _check_pactl()

    default_source = get_default_source()
    default_sink = get_default_sink()

    # Try JSON format first (newer pactl)
    raw = _get_sources_json()
    if raw is not None:
        return parse_sources(raw, default_source, default_sink)

    # Fallback to short format
    devices = _get_sources_short()
    for d in devices:
        d["is_default"] = d["name"] == default_source or (
            default_sink and d["name"] == f"{default_sink}.monitor"
        )
    return devices


def get_input_devices() -> list[dict[str, Any]]:
    """Return only input (microphone) devices."""
    return [d for d in get_audio_devices() if d["kind"] == "input"]


def get_monitor_devices() -> list[dict[str, Any]]:
    """Return only monitor (system audio loopback) devices."""
    return [d for d in get_audio_devices() if d["kind"] == "monitor"]


def resolve_mic_source(cfg_mic_source: str | None) -> str:
    """Resolve mic_source config value to an actual device name.

    - "auto" or None/empty → best default input device
    - saved name → that device if still exists, else fallback + notice
    """
    if not cfg_mic_source or cfg_mic_source == "auto":
        return _auto_mic_source()

    # Validate saved device exists and is an input
    devices = get_audio_devices()
    for d in devices:
        if d["name"] == cfg_mic_source and d["kind"] == "input":
            return cfg_mic_source

    # Saved device gone or wrong kind → fallback
    return _auto_mic_source()


def resolve_system_source(cfg_system_source: str | None) -> str:
    """Resolve system_source config value to an actual device name.

    - "auto" or None/empty → default sink's monitor
    - saved name → that device if still exists and is a monitor, else fallback
    """
    if not cfg_system_source or cfg_system_source == "auto":
        return _auto_system_source()

    devices = get_audio_devices()
    for d in devices:
        if d["name"] == cfg_system_source and d["kind"] == "monitor":
            return cfg_system_source

    return _auto_system_source()


def _auto_mic_source() -> str:
    """Pick the best available input device for microphone."""
    devices = get_input_devices()
    if not devices:
        raise RuntimeError("No input (microphone) devices found")

    # Prefer default source if it's an input
    for d in devices:
        if d["is_default"]:
            return d["name"]

    # Else first available input (prefer non-virtual, but we don't have that info)
    return devices[0]["name"]


def _auto_system_source() -> str:
    """Pick the best available monitor device for system audio."""
    default_sink = get_default_sink()
    if default_sink:
        monitor_name = f"{default_sink}.monitor"
        devices = get_monitor_devices()
        for d in devices:
            if d["name"] == monitor_name:
                return monitor_name
    # Fallback: first monitor
    devices = get_monitor_devices()
    if not devices:
        raise RuntimeError("No monitor (system audio) devices found")
    return devices[0]["name"]


def list_sources_for_cli() -> list[dict[str, Any]]:
    """Return sources in the legacy CLI shape: name, description, auto."""
    devices = get_audio_devices()
    out = []
    for d in devices:
        out.append({"name": d["name"], "description": d["description"], "auto": d["is_default"]})
    return out