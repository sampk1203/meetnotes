"""Tests for transcribe module."""

from meetnotes.transcribe import resolve_device, merge_segments, Segment


def test_resolve_device_auto_cuda():
    """Auto device picks cuda when available."""
    # We can't guarantee CUDA here, so just check the function returns a tuple
    class FakeCfg:
        whisper_device = "auto"
        whisper_compute_type = "auto"
    device, ct = resolve_device(FakeCfg())
    assert device in ("cuda", "cpu")
    assert ct in ("int8_float16", "int8")


def test_resolve_device_explicit():
    class FakeCfg:
        whisper_device = "cpu"
        whisper_compute_type = "int8"
    device, ct = resolve_device(FakeCfg())
    assert device == "cpu"
    assert ct == "int8"


def test_merge_segments():
    a = [Segment("Me", "hello", 0.0, 1.0)]
    b = [Segment("Others", "hi", 0.5, 1.5)]
    merged = merge_segments(a, b)
    assert len(merged) == 2
    assert merged[0].start == 0.0
    assert merged[1].start == 0.5
