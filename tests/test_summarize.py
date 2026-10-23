"""Tests for summarize module."""

import json
import pytest
from unittest.mock import patch, MagicMock

from meetnotes.summarize import _parse, _chunk_text


def test_parse_valid_json():
    data = {"title": "Test", "summary": "Summary text", "decisions": [], "action_items": [], "open_questions": []}
    result = _parse(json.dumps(data))
    assert result["title"] == "Test"
    assert result["summary"] == "Summary text"


def test_parse_with_code_fence():
    raw = "```json\n" + json.dumps({"title": "Fenced", "summary": "s", "decisions": [], "action_items": [], "open_questions": []}) + "\n```"
    result = _parse(raw)
    assert result["title"] == "Fenced"


def test_parse_invalid_json_fallback():
    result = _parse("not json at all")
    assert result["title"] == "not json at all"


def test_chunk_text():
    """Long text with newlines splits into multiple chunks."""
    # Create text with many lines to exceed max_chars
    long_text = "\n".join(f"[{i}.0-{i+1}.0] Speaker: " + "x" * 300 for i in range(50))
    chunks = _chunk_text(long_text, 10000)
    assert len(chunks) >= 2
    assert all(len(c) > 0 for c in chunks)


def test_chunk_text_small():
    chunks = _chunk_text("small", 10000)
    assert chunks == ["small"]


def test_chunk_text_hard_splits_oversized_segment():
    """A single segment longer than max_chars is hard-split."""
    long_line = "x" * 5000
    text = f"[0.0-10.0] Speaker: {long_line}"
    chunks = _chunk_text(text, 3000)
    assert all(len(c) <= 3000 for c in chunks)
    assert len(chunks) >= 2


def test_chunk_text_normal_split():
    """Text split by newlines into multiple chunks stays under limit."""
    long_text = "\n".join(f"[{i}.0-{i+1}.0] Speaker: " + "x" * 300 for i in range(50))
    chunks = _chunk_text(long_text, 10000)
    assert all(len(c) <= 10000 for c in chunks)
    assert len(chunks) >= 2


def test_summarize_calls_llm_once_for_short():
    """Short transcript goes through single-path, not map-reduce."""
    import os
    os.environ["K"] = "test-key"
    try:
        from meetnotes.summarize import summarize

        fake_resp = MagicMock()
        fake_resp.choices = [MagicMock(message=MagicMock(content=json.dumps({
            "title": "T", "summary": "S", "decisions": [], "action_items": [], "open_questions": []
        })))]

        fake_client = MagicMock()
        fake_client.chat.completions.create.return_value = fake_resp

        with patch("meetnotes.summarize.OpenAI", return_value=fake_client):
            result = summarize("short text", MagicMock(llm_base_url="http://x", llm_api_key_env="K", llm_model="m", llm_chunk_chars=1000))
        assert result["title"] == "T"
    finally:
        del os.environ["K"]


def test_summarize_map_reduce_path():
    """Long transcript triggers map-reduce: two LLM calls."""
    import os
    os.environ["K"] = "test-key"
    try:
        from meetnotes.summarize import summarize

        # Text with 50 × 500-char lines → 6 chunks + 1 merge = 7 total LLM calls
        chunk_resp = MagicMock()
        chunk_resp.choices = [MagicMock(message=MagicMock(content=json.dumps({
            "title": "C", "summary": "Chunk summary", "decisions": [], "action_items": [], "open_questions": []
        })))]

        final_resp = MagicMock()
        final_resp.choices = [MagicMock(message=MagicMock(content=json.dumps({
            "title": "Final", "summary": "Final summary", "decisions": [], "action_items": [], "open_questions": []
        })))]

        fake_client = MagicMock()
        fake_client.chat.completions.create.side_effect = [chunk_resp] * 6 + [final_resp]

        long_text = "\n".join(f"[{i}.0-{i+1}.0] Speaker: " + "x" * 500 for i in range(50))

        with patch("meetnotes.summarize.OpenAI", return_value=fake_client):
            result = summarize(long_text, MagicMock(llm_base_url="http://x", llm_api_key_env="K", llm_model="m", llm_chunk_chars=5000))

        assert result["title"] == "Final"
        assert fake_client.chat.completions.create.call_count == 7
    finally:
        del os.environ["K"]


def test_summarize_llm_failure_after_retries():
    """After 3 retries, LLM failure raises but caller should still write transcript."""
    import os
    os.environ["K"] = "test-key"
    try:
        from meetnotes.summarize import summarize

        fake_client = MagicMock()
        fake_client.chat.completions.create.side_effect = Exception("API down")

        with patch("meetnotes.summarize.OpenAI", return_value=fake_client):
            with pytest.raises(Exception, match="API down"):
                summarize("short text", MagicMock(llm_base_url="http://x", llm_api_key_env="K", llm_model="m", llm_chunk_chars=1000))

        # Verify 3 retries attempted
        assert fake_client.chat.completions.create.call_count == 3
    finally:
        del os.environ["K"]
