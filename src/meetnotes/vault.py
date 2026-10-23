from __future__ import annotations

import os
import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any


def _sanitize_title(title: str) -> str:
    """Make title safe for filenames."""
    # Keep alphanumeric, spaces, hyphens, underscores
    cleaned = re.sub(r"[^\w\s\-]", "", title)
    cleaned = cleaned.strip()
    return cleaned[:100]  # reasonable max length


def _find_unique_path(base: Path) -> Path:
    """Return base if it doesn't exist, else base_1, base_2, ..."""
    if not base.exists():
        return base
    stem = base.stem
    suffix = base.suffix
    parent = base.parent
    counter = 1
    while True:
        candidate = parent / f"{stem}_{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def write_note(cfg: Any, title: str, result: dict[str, Any]) -> dict[str, Path]:
    """
    Write meeting note and transcript to Obsidian vault.
    Returns dict with 'note_path' and 'transcript_path'.
    """
    vault = Path(cfg.vault_path).expanduser() / cfg.folder
    vault.mkdir(parents=True, exist_ok=True)

    now = datetime.now()
    date_str = now.strftime("%Y-%m-%d %H%M")
    safe_title = _sanitize_title(title)
    filename = f"{date_str} - {safe_title}.md"
    transcript_filename = f"{date_str} - {safe_title} - transcript.md"

    note_path = _find_unique_path(vault / filename)
    transcript_path = _find_unique_path(vault / transcript_filename)

    # Write transcript first
    segments = result.get("segments", [])
    transcript_lines = [f"# {title}", "", f"**Date:** {now.strftime('%Y-%m-%d %H:%M')}"]
    if segments:
        transcript_lines.append(f"**Duration:** {result.get('duration', 0):.1f}s")
        transcript_lines.append("")
        for s in segments:
            transcript_lines.append(f"[{s.start:.1f}-{s.end:.1f}] **{s.speaker}**: {s.text}")

    # Write both atomically; delete transcript on failure
    tmp_transcript = None
    try:
        fd, tmp_transcript = tempfile.mkstemp(dir=vault, suffix=".tmp")
        with os.fdopen(fd, "w") as f:
            f.write("\n".join(transcript_lines) + "\n")
        os.replace(tmp_transcript, transcript_path)
        tmp_transcript = None
    finally:
        if tmp_transcript and os.path.exists(tmp_transcript):
            os.unlink(tmp_transcript)

    # Write note
    summary = result.get("summary", "")
    frontmatter = [
        "---",
        f"title: \"{title}\"",
        f"date: {now.isoformat()}",
        f"duration: {result.get('duration', 0):.1f}",
        "type: meeting",
        "tags: [meeting]",
        "source: meetnotes",
        "---",
        "",
    ]
    note_lines = frontmatter + [summary, "", f"[[{transcript_path.name}]]"]

    _atomic_write(note_path, "\n".join(note_lines) + "\n")

    return {"note_path": note_path, "transcript_path": transcript_path}


def _atomic_write(path: Path, content: str) -> None:
    """Write content atomically via temp file + rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(content)
        os.replace(tmp, path)
    except Exception:
        os.unlink(tmp)
        raise
