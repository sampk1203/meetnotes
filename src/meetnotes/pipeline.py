"""Pipeline: transcribe → summarize → vault."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from meetnotes.transcribe import transcribe_single, merge_segments, Segment
from meetnotes.summarize import summarize
from meetnotes.vault import write_note
from faster_whisper import WhisperModel


def run_pipeline(
    mic_path: Path,
    system_path: Path | None,
    cfg: Any,
    title: str | None = None,
    no_llm: bool = False,
) -> dict[str, Any]:
    """Run full pipeline and return result dict with note_path and transcript_path.

    If keep_audio is False (default), deletes WAV files after successful run.
    """
    # Load model once for both tracks to save VRAM and time (4 GB constraint)
    from meetnotes.transcribe import resolve_device
    device, compute_type = resolve_device(cfg)
    whisper_model = WhisperModel(cfg.whisper_model, device=device, compute_type=compute_type)

    try:
        mic_result = transcribe_single(mic_path, cfg, speaker="Me", model=whisper_model)
        segments: list[Segment] = mic_result["segments"]

        if system_path and system_path.exists():
            sys_result = transcribe_single(system_path, cfg, speaker="Others", model=whisper_model)
            segments = merge_segments(segments, sys_result["segments"])
    finally:
        del whisper_model
        import gc
        gc.collect()

    duration = sum(s.end - s.start for s in segments)
    full_text = "\n".join(f"[{s.start:.1f}-{s.end:.1f}] {s.speaker}: {s.text}" for s in segments)

    if no_llm:
        summary_title = title or "Untitled Meeting"
        summary = full_text
    else:
        llm_result = summarize(full_text, cfg)
        summary_title = str(llm_result.get("title") or "Untitled Meeting")
        summary = _format_summary(llm_result)

    final_title = str(title) if title else summary_title
    vault_result = write_note(cfg, final_title, {
        "segments": segments,
        "summary": summary,
        "duration": duration,
    })

    # Delete audio files unless keep_audio is True
    if not cfg.keep_audio:
        mic_path.unlink(missing_ok=True)
        if system_path:
            system_path.unlink(missing_ok=True)
        # Clean up empty folder
        out_dir = mic_path.parent
        try:
            out_dir.rmdir()
        except OSError:
            pass  # Folder not empty (other files present)

    return {
        "segments": segments,
        "title": final_title,
        "duration": duration,
        "note_path": vault_result["note_path"],
        "transcript_path": vault_result["transcript_path"],
    }


def _format_summary(result: dict[str, Any]) -> str:
    """Format LLM result dict as markdown."""
    lines = [f"# {result.get('title', 'Meeting')}"]
    lines.append("")
    lines.append("## Summary")
    lines.append(result.get("summary", ""))
    lines.append("")
    decisions = result.get("decisions", [])
    if decisions:
        lines.append("## Decisions")
        lines.extend(f"- {d}" for d in decisions)
        lines.append("")
    action_items = result.get("action_items", [])
    if action_items:
        lines.append("## Action Items")
        lines.extend(action_items)
        lines.append("")
    questions = result.get("open_questions", [])
    if questions:
        lines.append("## Open Questions")
        lines.extend(f"- {q}" for q in questions)
    return "\n".join(lines) + "\n"
