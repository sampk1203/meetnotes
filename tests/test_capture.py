"""Tests for capture module."""

import threading
import wave
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from meetnotes.capture import (
    _build_parec_args,
    _pcm_to_wav,
    recover_recordings,
    start_recording,
)
from meetnotes.audio_devices import list_sources_for_cli


def test_list_sources_mocked():
    """Test source parsing without actual pactl."""
    with patch("meetnotes.audio_devices.shutil.which", return_value="/usr/bin/pactl"):
        with patch("subprocess.check_output") as mock_check:
            mock_check.side_effect = lambda cmd, **_kw: {
                ("pactl", "get-default-source"): "alsa_input.pci-0000_00_1f.3.analog-stereo\n",
                ("pactl", "get-default-sink"): "alsa_output.pci-0000_00_1f.3.analog-stereo\n",
                ("pactl", "list", "short", "sources"): (
                    "0\talsa_input.pci-0000_00_1f.3.analog-stereo\tmodule-alsa-card.c\ts16le 2ch 44100Hz\tIDLE\n"
                    "1\talsa_output.pci-0000_00_1f.3.analog-stereo.monitor\tmodule-alsa-card.c\ts16le 2ch 44100Hz\tIDLE\n"
                ),
            }.get(tuple(cmd), "")

            sources = list_sources_for_cli()
            assert len(sources) == 2
            assert any(s["auto"] for s in sources)


class _FakeProc:
    def __init__(self, _args, stdout):
        # Write 200 frames of silence (s16le mono = 400 bytes)
        if stdout is not None:
            stdout.write(b"\x00\x00" * 200)
            stdout.flush()
        self._alive = True

    def poll(self):
        return None if self._alive else 0

    def terminate(self):
        self._alive = False

    def wait(self, timeout=None):
        return 0


def test_start_recording_in_worker_thread_stops_on_event(tmp_path):
    """Regression: signal.signal() must not be called off the main thread."""
    cfg = SimpleNamespace(
        recordings_dir=str(tmp_path), mic_source="mic", system_source="sys.monitor"
    )
    stop = threading.Event()
    result: dict = {}

    def worker():
        try:
            result["paths"] = start_recording(cfg, stop)
        except Exception as exc:  # noqa: BLE001
            result["exc"] = exc

    fake_devices = [
        {"name": "mic", "kind": "input", "is_default": False},
        {"name": "sys.monitor", "kind": "monitor", "is_default": False},
    ]
    with patch("meetnotes.audio_devices.get_audio_devices", return_value=fake_devices), patch(
        "meetnotes.audio_devices.shutil.which", return_value="/usr/bin/x"
    ), patch("meetnotes.capture.subprocess.Popen", _FakeProc):
        t = threading.Thread(target=worker)
        t.start()
        stop.set()
        t.join(timeout=5)

    assert not t.is_alive()
    assert "exc" not in result, result.get("exc")
    mic, system = result["paths"]
    assert mic.exists() and system.exists()


def test_build_parec_args_uses_raw():
    """_build_parec_args must output raw PCM, not WAV, to avoid header issues."""
    args = _build_parec_args("test_device")
    assert "--raw" in args
    assert "--file-format" not in args
    assert args.count("test_device") == 1


def test_pcm_to_wav_produces_valid_wave(tmp_path):
    """Raw PCM bytes should become a valid WAV readable by wave module."""
    pcm_data = b"\x00\x00" * 100  # 100 frames of silence, s16le mono
    pcm = tmp_path / "test.pcm"
    wav = tmp_path / "test.wav"
    pcm.write_bytes(pcm_data)

    _pcm_to_wav(pcm, wav)

    assert wav.exists()
    assert not pcm.exists()  # .pcm should be deleted
    with wave.open(str(wav), "rb") as w:
        assert w.getnchannels() == 1
        assert w.getsampwidth() == 2
        assert w.getframerate() == 16000
        assert w.getnframes() == 100


def test_recover_recordings_finds_orphan_pcm(tmp_path):
    """recover_recordings should wrap orphan .pcm files into .wav."""
    pcm = tmp_path / "orphan.pcm"
    pcm.write_bytes(b"\x00\x00" * 50)

    recovered = recover_recordings(tmp_path)

    assert len(recovered) == 1
    assert recovered[0].suffix == ".wav"
    assert not pcm.exists()


def test_recover_recordings_skips_broken_file(tmp_path):
    """recover_recordings should not crash on corrupted .pcm."""
    # Write odd number of bytes - s16le requires pairs, but wave module
    # accepts any byte count, so this test validates the try/except path
    # by simulating a file that would cause an error in the WAV consumer.
    bad = tmp_path / "bad.pcm"
    bad.write_bytes(b"\x00" * 3)  # odd bytes - malformed s16le frame

    # recover_recordings should not crash; it may or may not create a wav
    recovered = recover_recordings(tmp_path)
    # At minimum it should not raise


def test_recover_recordings_no_dir(tmp_path):
    """recover_recordings returns empty when directory doesn't exist."""
    assert recover_recordings(tmp_path / "nonexistent") == []


def test_start_recording_convert_pcm_to_wav(tmp_path):
    """start_recording should output .wav files even though parec writes .pcm."""
    cfg = SimpleNamespace(
        recordings_dir=str(tmp_path), mic_source="mic", system_source="sys.monitor"
    )

    class _ExitImmediatelyProc:
        def __init__(self, args, stdout):
            if stdout is not None:
                stdout.write(b"\x00\x00" * 10)
                stdout.flush()

        def poll(self):
            return 0  # exits immediately

        def terminate(self):
            pass

        def wait(self, timeout=None):
            return 0

    fake_devices = [
        {"name": "mic", "kind": "input", "is_default": False},
        {"name": "sys.monitor", "kind": "monitor", "is_default": False},
    ]
    with patch("meetnotes.audio_devices.get_audio_devices", return_value=fake_devices), patch(
        "meetnotes.audio_devices.shutil.which", return_value="/usr/bin/x"
    ), patch("meetnotes.capture.subprocess.Popen", _ExitImmediatelyProc):
        mic, system = start_recording(cfg)

    assert mic.suffix == ".wav"
    assert system.suffix == ".wav"
    assert not (mic.parent / "mic.pcm").exists()
    assert not (mic.parent / "system.pcm").exists()
    assert mic.stat().st_size > 0
    assert system.stat().st_size > 0


def test_start_recording_empty_wav_raises(tmp_path):
    """start_recording raises when recordings capture zero audio frames."""
    cfg = SimpleNamespace(
        recordings_dir=str(tmp_path), mic_source="mic", system_source="sys.monitor"
    )

    class _EmptyProc:
        def __init__(self, args, stdout=None):
            self._alive = True

        def poll(self):
            return 0  # exits immediately, writes nothing

        def terminate(self):
            self._alive = False

        def wait(self, timeout=None):
            return 0

    fake_devices = [
        {"name": "mic", "kind": "input", "is_default": False},
        {"name": "sys.monitor", "kind": "monitor", "is_default": False},
    ]
    with patch("meetnotes.audio_devices.get_audio_devices", return_value=fake_devices), patch(
        "meetnotes.audio_devices.shutil.which", return_value="/usr/bin/x"
    ), patch("meetnotes.capture.subprocess.Popen", _EmptyProc):
        with pytest.raises(RuntimeError, match="Empty recording"):
            start_recording(cfg)
