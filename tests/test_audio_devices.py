"""Tests for audio_devices module."""

import json
from types import SimpleNamespace
from unittest.mock import patch

from meetnotes.audio_devices import (
    get_audio_devices,
    get_input_devices,
    get_monitor_devices,
    list_sources_for_cli,
    parse_sources,
    resolve_mic_source,
    resolve_system_source,
    _auto_mic_source,
    _auto_system_source,
)


def _make_pactl_json_response(sources: list[dict]) -> list[dict]:
    """Wrap a list of source dicts into the pactl --format=json list sources structure."""
    return sources


def test_parse_sources_json_input():
    """Parse pactl JSON into our canonical device format."""
    raw = _make_pactl_json_response(
        [
            {
                "index": 0,
                "name": "alsa_input.pci-0000_00_1f.3.analog-stereo",
                "properties": {
                    "device.description": "Built-in Audio Analog Stereo",
                    "device.class": "source",
                },
                "state": "RUNNING",
                "mute": False,
                "volume": {"values": [65536, 65536]},
            },
            {
                "index": 1,
                "name": "alsa_output.pci-0000_00_1f.3.analog-stereo.monitor",
                "properties": {
                    "device.description": "Monitor of Built-in Audio Analog Stereo",
                    "device.class": "monitor",
                },
                "state": "IDLE",
                "mute": True,
                "volume": {"values": [65536]},
            },
        ]
    )
    default_source = "alsa_input.pci-0000_00_1f.3.analog-stereo"
    default_sink = "alsa_output.pci-0000_00_1f.3.analog-stereo"

    devices = parse_sources(raw, default_source, default_sink)

    assert len(devices) == 2
    # First is input
    assert devices[0]["name"] == "alsa_input.pci-0000_00_1f.3.analog-stereo"
    assert devices[0]["kind"] == "input"
    assert devices[0]["description"] == "Built-in Audio Analog Stereo"
    assert devices[0]["is_default"] is True
    assert devices[0]["state"] == "RUNNING"
    assert devices[0]["muted"] is False
    assert devices[0]["volume"] == 65536

    # Second is monitor
    assert devices[1]["name"] == "alsa_output.pci-0000_00_1f.3.analog-stereo.monitor"
    assert devices[1]["kind"] == "monitor"
    assert devices[1]["description"] == "Monitor of Built-in Audio Analog Stereo"
    assert devices[1]["is_default"] is True
    assert devices[1]["state"] == "IDLE"
    assert devices[1]["muted"] is True


def test_get_input_devices_filters_kind():
    """get_input_devices should only return input devices."""
    with patch("meetnotes.audio_devices.get_audio_devices") as mock_get:
        mock_get.return_value = [
            {"name": "mic1", "kind": "input"},
            {"name": "monitor1", "kind": "monitor"},
            {"name": "mic2", "kind": "input"},
        ]
        inputs = get_input_devices()
        assert len(inputs) == 2
        assert all(d["kind"] == "input" for d in inputs)


def test_get_monitor_devices_filters_kind():
    """get_monitor_devices should only return monitor devices."""
    with patch("meetnotes.audio_devices.get_audio_devices") as mock_get:
        mock_get.return_value = [
            {"name": "mic1", "kind": "input"},
            {"name": "monitor1", "kind": "monitor"},
            {"name": "mic2", "kind": "input"},
        ]
        monitors = get_monitor_devices()
        assert len(monitors) == 1
        assert monitors[0]["kind"] == "monitor"


def test_resolve_mic_source_auto_picks_first_input():
    """resolve_mic_source('auto') picks the first available input."""
    with patch("meetnotes.audio_devices.get_input_devices") as mock_get:
        mock_get.return_value = [
            {"name": "input1", "kind": "input", "is_default": False},
            {"name": "input2", "kind": "input", "is_default": False},
        ]
        assert resolve_mic_source("auto") == "input1"
        assert resolve_mic_source(None) == "input1"
        assert resolve_mic_source("") == "input1"


def test_resolve_mic_source_prefers_default():
    """resolve_mic_source('auto') prefers default input if available."""
    with patch("meetnotes.audio_devices.get_input_devices") as mock_get:
        mock_get.return_value = [
            {"name": "input1", "kind": "input", "is_default": False},
            {"name": "default_input", "kind": "input", "is_default": True},
        ]
        assert resolve_mic_source("auto") == "default_input"


def test_resolve_mic_source_saved_device_still_exists():
    """resolve_mic_source returns saved name if device exists and is input."""
    with patch("meetnotes.audio_devices.get_audio_devices") as mock_get:
        mock_get.return_value = [
            {"name": "saved_mic", "kind": "input", "is_default": False},
            {"name": "other_input", "kind": "input", "is_default": True},
        ]
        assert resolve_mic_source("saved_mic") == "saved_mic"


def test_resolve_mic_source_saved_device_gone_fallback():
    """resolve_mic_source falls back to auto when saved device is gone."""
    with patch("meetnotes.audio_devices.get_audio_devices") as mock_get:
        mock_get.return_value = [
            {"name": "other_input", "kind": "input", "is_default": True},
        ]
        assert resolve_mic_source("nonexistent_mic") == "other_input"


def test_resolve_mic_source_saved_device_wrong_kind_fallback():
    """resolve_mic_source falls back if saved device is a monitor."""
    with patch("meetnotes.audio_devices.get_audio_devices") as mock_get:
        mock_get.return_value = [
            {"name": "saved_monitor", "kind": "monitor", "is_default": True},
            {"name": "real_input", "kind": "input", "is_default": False},
        ]
        assert resolve_mic_source("saved_monitor") == "real_input"


def test_resolve_system_source_auto_picks_default_sink_monitor():
    """resolve_system_source('auto') picks default sink's monitor."""
    with patch("meetnotes.audio_devices.get_monitor_devices") as mock_monitors, patch(
        "meetnotes.audio_devices.get_default_sink"
    ) as mock_sink:
        mock_sink.return_value = "sink1"
        mock_monitors.return_value = [
            {"name": "sink1.monitor", "kind": "monitor"},
            {"name": "sink2.monitor", "kind": "monitor"},
        ]
        assert resolve_system_source("auto") == "sink1.monitor"


def test_resolve_system_source_saved_monitor_still_exists():
    """resolve_system_source returns saved monitor if it exists."""
    with patch("meetnotes.audio_devices.get_audio_devices") as mock_get:
        mock_get.return_value = [
            {"name": "saved.monitor", "kind": "monitor"},
            {"name": "other.monitor", "kind": "monitor"},
        ]
        assert resolve_system_source("saved.monitor") == "saved.monitor"


def test_resolve_system_source_saved_monitor_gone_fallback():
    """resolve_system_source falls back when saved monitor is gone."""
    with patch("meetnotes.audio_devices.get_audio_devices") as mock_get, patch(
        "meetnotes.audio_devices.get_default_sink"
    ) as mock_sink:
        mock_sink.return_value = "default_sink"
        mock_get.return_value = [
            {"name": "default_sink.monitor", "kind": "monitor"},
        ]
        assert resolve_system_source("gone.monitor") == "default_sink.monitor"


def test_list_sources_for_cli_shape():
    """list_sources_for_cli returns legacy shape: name, description, auto."""
    with patch("meetnotes.audio_devices.get_audio_devices") as mock_get, patch(
        "meetnotes.audio_devices.get_default_source"
    ) as mock_src, patch(
        "meetnotes.audio_devices.get_default_sink"
    ) as mock_sink:
        mock_src.return_value = "default_mic"
        mock_sink.return_value = "default_sink"
        mock_get.return_value = [
            {
                "name": "default_mic",
                "description": "Default Mic",
                "kind": "input",
                "is_default": True,
            },
            {
                "name": "default_sink.monitor",
                "description": "Default Monitor",
                "kind": "monitor",
                "is_default": True,
            },
            {
                "name": "other_mic",
                "description": "Other Mic",
                "kind": "input",
                "is_default": False,
            },
        ]
        sources = list_sources_for_cli()
        assert len(sources) == 3
        for s in sources:
            assert "name" in s
            assert "description" in s
            assert "auto" in s
        assert sources[0]["auto"] is True
        assert sources[1]["auto"] is True
        assert sources[2]["auto"] is False


def test_parse_sources_fallback_short_format():
    """parse_sources fallback uses name suffix for kind when JSON not available."""
    # This tests the internal parsing logic; actual get_audio_devices handles fallback
    raw = _make_pactl_json_response(
        [
            {
                "index": 0,
                "name": "alsa_input.usb-headset.analog-stereo",
                "properties": {"device.description": "USB Headset"},
                "state": "SUSPENDED",
                "mute": False,
                "volume": {"values": [32768]},
            },
        ]
    )
    devices = parse_sources(raw, "default_mic", "default_sink")
    assert devices[0]["kind"] == "input"
    assert devices[0]["state"] == "SUSPENDED"
    assert devices[0]["muted"] is False
    assert devices[0]["volume"] == 32768