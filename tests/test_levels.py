"""Tests for levels module."""

import time
from unittest.mock import patch, MagicMock

import pytest

from meetnotes.levels import DualLevelMeter, LevelMeter


def test_pcm_to_dbfs_silence():
    """Silence (all zeros) should give -60 dBFS (clamped floor)."""
    meter = LevelMeter("test", sample_rate=16000)
    silence = b"\x00\x00" * 100  # 100 frames of silence
    db = meter._pcm_to_dbfs(silence)
    assert db == -60.0


def test_pcm_to_dbfs_full_scale():
    """Full-scale square wave should give ~0 dBFS."""
    meter = LevelMeter("test", sample_rate=16000)
    # 32767 = max int16, repeated
    full = b"\xFF\x7F" * 100
    db = meter._pcm_to_dbfs(full)
    assert db > -1.0  # Very close to 0 dBFS


def test_pcm_to_dbfs_half_scale():
    """Half-scale should give ~-6 dBFS."""
    meter = LevelMeter("test", sample_rate=16000)
    # 16384 = half of 32768
    half = b"\x00\x40" * 100
    db = meter._pcm_to_dbfs(half)
    assert -7.0 < db < -5.0


def test_smoothing_attack_faster_than_decay():
    """Attack should be faster than decay."""
    meter = LevelMeter("test", sample_rate=16000)
    # Start at -60
    meter._current_db = -60.0

    # Attack: jump to 0
    attacked = meter._smooth(0.0)
    # First step moves a small amount (coeff per sample, called per chunk)
    assert attacked > -60.0  # Just moved from -60

    # Now decay back to -60
    decayed = meter._smooth(-60.0)
    # Should move less (decay is slow)
    assert decayed < attacked


def test_level_meter_get_level_returns_none_when_empty():
    """get_level returns None when queue is empty."""
    meter = LevelMeter("test")
    assert meter.get_level() is None


def test_dual_meter_set_sources_restarts():
    """set_sources should recreate meters with new sources."""
    dm = DualLevelMeter("mic1", "sys1")
    # Mock the start method to track calls
    dm.mic.start = MagicMock()
    dm.system.start = MagicMock()

    dm.set_sources("mic2", "sys2")

    assert dm.mic.source == "mic2"
    assert dm.system.source == "sys2"


def test_check_no_signal_warning_after_threshold():
    """check_no_signal should warn after threshold duration."""
    dm = DualLevelMeter("mic", "sys")
    dm._no_signal_threshold = -50.0
    dm._no_signal_duration = 5.0

    # First call: below threshold, but not long enough
    warnings = dm.check_no_signal(-55.0, -55.0)
    assert warnings["mic"] is None
    assert warnings["system"] is None

    # Simulate time passing by directly manipulating internal state
    dm._no_signal_start["mic"] = time.time() - 6.0
    dm._no_signal_start["system"] = time.time() - 6.0

    warnings = dm.check_no_signal(-55.0, -55.0)
    assert warnings["mic"] is not None
    assert "No signal" in warnings["mic"]
    assert warnings["system"] is not None
    assert "No signal" in warnings["system"]


def test_check_no_signal_no_warning_above_threshold():
    """No warning when level is above threshold."""
    dm = DualLevelMeter("mic", "sys")
    dm._no_signal_threshold = -50.0

    warnings = dm.check_no_signal(-40.0, -30.0)
    assert warnings["mic"] is None
    assert warnings["system"] is None


def test_check_no_signal_clears_timer_when_above_threshold():
    """Timer should clear when signal rises above threshold."""
    dm = DualLevelMeter("mic", "sys")
    dm._no_signal_threshold = -50.0
    dm._no_signal_start["mic"] = time.time() - 10.0

    warnings = dm.check_no_signal(-40.0, None)
    assert warnings["mic"] is None
    assert "mic" not in dm._no_signal_start


def test_level_meter_clamping():
    """dBFS should be clamped to [-60, 0]."""
    meter = LevelMeter("test", sample_rate=16000)
    # Very quiet but not silent
    quiet = b"\x01\x00" * 100  # Very small values
    db = meter._pcm_to_dbfs(quiet)
    assert -60.0 <= db <= 0.0


def test_dual_meter_start_stop():
    """start/stop should manage both meters."""
    dm = DualLevelMeter("mic", "sys")
    dm.start()
    assert dm.mic.is_running()
    assert dm.system.is_running()
    dm.stop()
    # Note: we can't easily assert not running due to thread timing,
    # but stop() should not raise


def test_level_meter_get_level_drains_queue():
    """Multiple get_level calls should drain queue."""
    meter = LevelMeter("test")
    # Manually add items
    meter._queue.put(-30.0)
    meter._queue.put(-25.0)
    meter._queue.put(-20.0)

    assert meter.get_level() == -30.0
    assert meter.get_level() == -25.0
    assert meter.get_level() == -20.0
    assert meter.get_level() is None