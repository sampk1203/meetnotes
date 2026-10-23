# CHANGELOG

## Unreleased (v0.2.0)

- **P1: Capture robustness** — parec now writes raw PCM (`--raw` → `.pcm`) and stdlib `wave` wraps each `.pcm` into a valid `.wav` on stop, avoiding libsndfile header-flush issues on SIGTERM
- New `capture.recover_recordings()` scans `recordings_dir` for orphan `.pcm` left by crashes and wraps them as `.wav`
- GUI `closeEvent` + `atexit` hook calls `_cleanup_at_exit()`: sets stop event, joins worker thread, then recovers orphan PCM
- Empty-recording check moved to `.pcm` size; zero-byte audio produces a valid 44-byte WAV (0 frames) rather than failing
- Fix: test `_EmptyProc.wait()` parameter name collision with `start_recording`'s `timeout` kwarg
- Tests: 7 new unit tests — PCM→WAV roundtrip, orphan recovery, broken file skip, empty-file handling

- **P2: Device listing + classification** — New `audio_devices.py` module using `pactl --format=json` for richer device info (kind, state, mute, volume, description)
- Structural fix for F4: mic dropdown shows only input devices, system dropdown shows only monitors
- Smart defaults: mic prefers default source if it's an input; system prefers default sink's monitor
- Graceful fallback when saved device disappears (e.g., BT headset disconnected)
- Added 13 new unit tests for device parsing, filtering, and resolution

- **P3: Level meter + setup panel** — New `levels.py` module with `LevelMeter` and `DualLevelMeter` classes
- Real-time level metering: peak dBFS computed from raw PCM chunks (~10 Hz update)
- Fast attack / slow decay smoothing for readable bar movement
- "No signal" warning after 5 seconds of silence (below -50 dBFS floor)
- GUI dropdowns populated at launch with live level bars; device choice persisted to config.toml (only `[audio]` keys updated)
- Added 12 new unit tests for level math, smoothing, and no-signal detection

- **P4: Recordings management** — New `recordings.py` module for scanning and managing recordings
- `scan_recordings()`: discovers ok/recoverable/empty recordings, computes duration from WAV header
- `last_recording()`: helper to find most recent complete recording
- `safe_delete()`: refuses paths outside recordings_dir, symlink escapes; deletes only known files
- GUI: added "Process last recording" button, "Open recordings folder" button
- Added 11 new unit tests for scanning, duration formatting, safe delete logic

- **Audit fixes (post-v0.2.0-beta)**
- Fix: `--no-gui` flag now works; `meetnotes start --no-gui` runs headless CLI recording loop
- Fix: `keep_audio` config key now implemented; audio deleted after pipeline when False, kept when True
- Fix: GUI no longer crashes on launch when saved device is gone (try/except around device loading)
- Fix: `safe_delete()` uses `pathlib.Path.is_relative_to()` for robust path validation
- Fix: `_pcm_to_wav()` streams in 8KB chunks to avoid 200MB RAM spike on long recordings
- Removed dead `window_picker.py` (F8) and its test
- Added 2 new pipeline tests for `keep_audio` behavior
- **Second audit fixes**
- Fix: Processing button now disabled during pipeline (prevents dual Whisper load → OOM on 4GB GPU)
- Fix: `_worker_thread` now stores the actual daemon thread object, not the GUI thread
- Fix: `_save_device_selection()` always writes config (removed `cfg_path.exists()` guard)
- Fix: `_process_last()` uses `recordings.last_recording()` instead of manual directory scan
- Fix: `audio_devices.list_sources_for_cli()` reuses `d["is_default"]` instead of re-calling `get_default_source/sink`
- Fix: `_chunk_text()` now hard-splits oversized single segments that exceed `max_chars`
- Fix: `_chunk_text()` uses list join instead of repeated string concatenation
- Fix: `_cuda_available()` caches torch import on first call (avoids 200ms per transcribe)
- Fix: Added missing `from typing import Any` in gui.py
- Tests: 2 new summarize tests for oversized segment splitting and normal split correctness

## Previous

- Fix: GUI Record failed with "signal only works in main thread"; `start_recording` now only installs the SIGINT handler in the main thread
- `start_recording(cfg, stop_event=None)`: recording can be stopped from any thread
- Fix: GUI Stop now ends recording and runs the pipeline (previously only reset the UI)
- Fix: `meetnotes process` crashed with "open() got an unexpected keyword argument 'metadata_errors'"; pin `av<19` (av 19 dropped the kwarg faster-whisper 1.2.x passes)
- Test: capture works in a worker thread and stops on event

## v0.1.0

- Initial scaffold: project structure, config, vault writer
- CLI: init, sources, start, process, download-model
- Config loading with defaults + TOML file support
- Vault: Obsidian markdown with YAML frontmatter, atomic writes, no-overwrite suffixing
- Capture: Linux pactl/parec integration, source discovery
- Pipeline: transcribe → summarize → vault
- GUI: Dark-mode PyQt6 app with record/stop, timer, window picker
- Tests: config, vault, capture mocking
