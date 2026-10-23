"""LLM summarization with map-reduce and retry."""

from __future__ import annotations

import json
import os
import time
from typing import Any

from openai import OpenAI


SYSTEM_PROMPT = """You are a meeting assistant. Given a transcript with speaker labels,
produce structured markdown notes. Output valid JSON with these exact keys:
- title: short title (≤50 chars)
- summary: 2-4 sentence summary
- decisions: array of strings
- action_items: array of objects with "task" and optional "owner"
- open_questions: array of strings"""


def summarize(transcript: str, cfg: Any) -> dict[str, str | list]:
    """Summarize transcript via LLM. Validates API key before calling."""
    api_key = os.environ.get(cfg.llm_api_key_env, "")
    if not api_key:
        raise RuntimeError(f"API key env var '{cfg.llm_api_key_env}' is not set")
    client = OpenAI(base_url=cfg.llm_base_url, api_key=api_key)
    if len(transcript) <= cfg.llm_chunk_chars:
        return _call_llm(client, cfg.llm_model, transcript)
    chunks = _chunk_text(transcript, cfg.llm_chunk_chars)
    chunk_summaries = [str(_call_llm(client, cfg.llm_model, c)["summary"]) for c in chunks]
    merged = "\n".join(chunk_summaries)
    return _call_llm(client, cfg.llm_model, merged)


def _call_llm(client: OpenAI, model: str, text: str) -> dict[str, str | list]:
    """Single LLM call with exponential backoff (3 tries)."""
    prompt = f"{SYSTEM_PROMPT}\n\nTranscript:\n{text}"
    for attempt in range(3):
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
            )
            content = resp.choices[0].message.content or ""
            return _parse(content)
        except Exception as exc:
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)
    raise RuntimeError("should not reach")


def _parse(text: str) -> dict[str, str | list]:
    """Extract JSON from LLM response, handling markdown fences."""
    text = text.strip()
    if text.startswith("```"):
        lines = [l for l in text.split("\n") if not l.startswith("```")]
        text = "\n".join(lines)
    try:
        data = json.loads(text)
        return {
            "title": data.get("title", "Untitled Meeting"),
            "summary": data.get("summary", text),
            "decisions": data.get("decisions", []),
            "action_items": [
                f'- [ ] {a["task"]}' + (f' @{a["owner"]}' if a.get("owner") else "")
                for a in data.get("action_items", [])
            ],
            "open_questions": data.get("open_questions", []),
        }
    except json.JSONDecodeError:
        lines = text.split("\n")
        title = lines[0].lstrip("# ").strip() if lines else "Untitled Meeting"
        return {"title": title, "summary": text, "decisions": [], "action_items": [], "open_questions": []}


def _chunk_text(text: str, max_chars: int) -> list[str]:
    """Split text into chunks of at most max_chars, preserving segment boundaries."""
    if len(text) <= max_chars:
        return [text]
    # Split on segment boundaries: each line starts with "[timestamp]"
    lines = text.split("\n")
    chunks: list[str] = []
    current_lines: list[str] = []
    current_len = 0
    for line in lines:
        line_len = len(line) + 1  # +1 for newline
        if current_lines and current_len + line_len > max_chars:
            chunks.append("\n".join(current_lines))
            current_lines, current_len = [line], line_len
        else:
            current_lines.append(line)
            current_len += line_len
    if current_lines:
        chunks.append("\n".join(current_lines))
    # Hard-split any chunk that still exceeds max_chars (single oversized segment).
    # Split at word boundary to avoid fake timestamp prefix.
    result: list[str] = []
    for chunk in chunks:
        while len(chunk) > max_chars:
            split_idx = chunk.rfind(" ", 0, max_chars)
            if split_idx == -1:
                split_idx = max_chars
            result.append(chunk[:split_idx])
            chunk = chunk[split_idx:].lstrip()
        result.append(chunk)
    return result
