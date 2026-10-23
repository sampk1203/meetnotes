"""Tests for pipeline module."""

from unittest.mock import MagicMock, patch
from pathlib import Path

from meetnotes.pipeline import run_pipeline


def test_run_pipeline_no_llm():
    """Pipeline runs transcript-only path without calling LLM."""
    fake_cfg = MagicMock()
    fake_cfg.vault_path = "/tmp"
    fake_cfg.folder = "Meetings"
    fake_cfg.whisper_model = "small"
    fake_cfg.whisper_device = "cpu"
    fake_cfg.whisper_compute_type = "int8"
    fake_cfg.whisper_language = "en"
    fake_cfg.vad_filter = False
    fake_cfg.llm_base_url = "http://x"
    fake_cfg.llm_api_key_env = "K"
    fake_cfg.llm_model = "m"
    fake_cfg.llm_chunk_chars = 1000
    fake_cfg.mic_source = "test"
    fake_cfg.system_source = "test"
    fake_cfg.keep_audio = False
    fake_cfg.recordings_dir = "/tmp/rec"
    fake_cfg.gui_theme = "dark"
    fake_cfg.window_picker_timeout = 15

    fake_seg = MagicMock()
    fake_seg.start = 0.0
    fake_seg.end = 1.0
    fake_seg.text = "hello"
    fake_seg.speaker = "Me"

    with patch("meetnotes.pipeline.transcribe_single", return_value={"segments": [fake_seg], "duration": 1.0}):
        with patch("meetnotes.pipeline.summarize") as mock_sum:
            mock_sum.side_effect = Exception("should not be called")
            result = run_pipeline(
                Path("/tmp/mic.wav"),
                Path("/tmp/sys.wav"),
                fake_cfg,
                title="Test Meeting",
                no_llm=True,
            )
    assert result["title"] == "Test Meeting"
    assert result["note_path"].exists()


def test_run_pipeline_deletes_audio_when_keep_audio_false(tmp_path):
    """Pipeline deletes WAV files after successful run when keep_audio=False."""
    fake_cfg = MagicMock()
    fake_cfg.vault_path = str(tmp_path)
    fake_cfg.folder = "Meetings"
    fake_cfg.whisper_model = "small"
    fake_cfg.whisper_device = "cpu"
    fake_cfg.whisper_compute_type = "int8"
    fake_cfg.whisper_language = "en"
    fake_cfg.vad_filter = False
    fake_cfg.llm_base_url = "http://x"
    fake_cfg.llm_api_key_env = "K"
    fake_cfg.llm_model = "m"
    fake_cfg.llm_chunk_chars = 1000
    fake_cfg.mic_source = "test"
    fake_cfg.system_source = "test"
    fake_cfg.keep_audio = False
    fake_cfg.recordings_dir = str(tmp_path / "rec")
    fake_cfg.gui_theme = "dark"
    fake_cfg.window_picker_timeout = 15

    # Create test audio files
    mic_path = tmp_path / "mic.wav"
    sys_path = tmp_path / "system.wav"
    mic_path.write_bytes(b"\x00\x00" * 10)
    sys_path.write_bytes(b"\x00\x00" * 10)

    fake_seg = MagicMock()
    fake_seg.start = 0.0
    fake_seg.end = 1.0
    fake_seg.text = "hello"
    fake_seg.speaker = "Me"

    with patch("meetnotes.pipeline.transcribe_single", return_value={"segments": [fake_seg], "duration": 1.0}):
        with patch("meetnotes.pipeline.summarize") as mock_sum:
            mock_sum.side_effect = Exception("should not be called")
            run_pipeline(mic_path, sys_path, fake_cfg, no_llm=True)

    # Audio files should be deleted
    assert not mic_path.exists()
    assert not sys_path.exists()


def test_run_pipeline_keeps_audio_when_keep_audio_true(tmp_path):
    """Pipeline keeps WAV files after successful run when keep_audio=True."""
    fake_cfg = MagicMock()
    fake_cfg.vault_path = str(tmp_path)
    fake_cfg.folder = "Meetings"
    fake_cfg.whisper_model = "small"
    fake_cfg.whisper_device = "cpu"
    fake_cfg.whisper_compute_type = "int8"
    fake_cfg.whisper_language = "en"
    fake_cfg.vad_filter = False
    fake_cfg.llm_base_url = "http://x"
    fake_cfg.llm_api_key_env = "K"
    fake_cfg.llm_model = "m"
    fake_cfg.llm_chunk_chars = 1000
    fake_cfg.mic_source = "test"
    fake_cfg.system_source = "test"
    fake_cfg.keep_audio = True
    fake_cfg.recordings_dir = str(tmp_path / "rec")
    fake_cfg.gui_theme = "dark"
    fake_cfg.window_picker_timeout = 15

    # Create test audio files
    mic_path = tmp_path / "mic.wav"
    sys_path = tmp_path / "system.wav"
    mic_path.write_bytes(b"\x00\x00" * 10)
    sys_path.write_bytes(b"\x00\x00" * 10)

    fake_seg = MagicMock()
    fake_seg.start = 0.0
    fake_seg.end = 1.0
    fake_seg.text = "hello"
    fake_seg.speaker = "Me"

    with patch("meetnotes.pipeline.transcribe_single", return_value={"segments": [fake_seg], "duration": 1.0}):
        with patch("meetnotes.pipeline.summarize") as mock_sum:
            mock_sum.side_effect = Exception("should not be called")
            run_pipeline(mic_path, sys_path, fake_cfg, no_llm=True)

    # Audio files should be kept
    assert mic_path.exists()
    assert sys_path.exists()
