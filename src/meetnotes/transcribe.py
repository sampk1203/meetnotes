"""Transcription via faster-whisper."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class Segment:
    speaker: str
    text: str
    start: float
    end: float


# torch is a transitive dep via faster-whisper; import lazily to avoid
# MissingModule errors when tests run in environments without GPU deps.
_cuda_cache: bool | None = None


def _cuda_available() -> bool:
    global _cuda_cache
    if _cuda_cache is not None:
        return _cuda_cache
    try:
        import torch
        _cuda_cache = bool(torch.cuda.is_available())
    except Exception:
        _cuda_cache = False
    return _cuda_cache


def resolve_device(cfg: Any) -> tuple[str, str]:
    """Resolve device and compute_type from config with 'auto' semantics."""
    device = cfg.whisper_device
    if device == "auto":
        device = "cuda" if _cuda_available() else "cpu"
    compute_type = cfg.whisper_compute_type
    if compute_type == "auto":
        compute_type = "int8_float16" if device == "cuda" else "int8"
    return device, compute_type


def transcribe_single(
    audio_path: Path,
    cfg: Any,
    speaker: str = "Speaker",
    model=None,
) -> dict[str, Any]:
    """Transcribe a single audio file. Returns {segments, duration}.

    Pass an existing model to avoid reloading between tracks (4 GB VRAM constraint).
    """
    from faster_whisper import WhisperModel

    device, compute_type = resolve_device(cfg)
    release = False
    if model is None:
        model = WhisperModel(cfg.whisper_model, device=device, compute_type=compute_type)
        release = True
    segments, info = model.transcribe(
        str(audio_path),
        language=cfg.whisper_language if cfg.whisper_language != "auto" else None,
        vad_filter=cfg.vad_filter,
        word_timestamps=False,
    )
    result = [
        Segment(speaker=speaker, text=s.text.strip(), start=s.start, end=s.end)
        for s in segments
    ]
    if release:
        del model
        import gc
        gc.collect()
    return {"segments": result, "duration": info.duration}


def merge_segments(mic: list[Segment], system: list[Segment]) -> list[Segment]:
    """Merge two sorted segment lists by start time."""
    merged = mic + system
    merged.sort(key=lambda s: s.start)
    return merged


def download_model(cfg: Any) -> None:
    """Download the configured Whisper model by loading it once."""
    from faster_whisper import WhisperModel
    device, compute_type = resolve_device(cfg)
    print(f"Downloading/verifying model '{cfg.whisper_model}'...")
    WhisperModel(cfg.whisper_model, device=device, compute_type=compute_type)
    print(f"Model '{cfg.whisper_model}' ready.")
