# meetnotes v0.2 plan

Status: **plan only, nothing implemented.** Confirm the decisions in section 7 before any edits.

## 1. Why we're doing this (findings so far)

| # | Finding | Evidence |
|---|---------|----------|
| F1 | GUI crashed on Record: `signal.signal()` called from a worker thread | `capture.py` + `gui.py` (fixed already: `stop_event`, main-thread-only SIGINT handler) |
| F2 | `av` 19 broke `faster-whisper` 1.2.1 (`metadata_errors` kwarg) | fixed already: `av<19` pin |
| F3 | Recordings come out as 0-byte WAVs. `parec --file-format wav` (libsndfile) only writes data on a clean close, SIGTERM loses it. `--raw` to a file works (64000 B in 3 s) | manual `parec` tests |
| F4 | Mic auto-pick can silently select a speaker `.monitor` (no real input flagged auto, so it falls back to `sources[0]`, which was `alsa_output...monitor`) | `meetnotes sources` output + `start_recording` logic |
| F5 | Crashed runs leave orphan `parec` processes (14 found) | `pgrep -a parec` |
| F6 | GUI Stop now auto-runs the full pipeline; no way to re-process, pick an old recording, or clean up audio | current GUI |
| F7 | `keep_audio` config key exists but is never read | grep |
| F8 | README claims the GUI has a window picker; `window_picker.py` is not wired into the GUI | grep |
| F9 | `meetnotes start --no-gui` still launches the GUI (`run_gui()` is unconditional) | `cli.py` |

F7-F9 are noted, **out of scope** unless you say otherwise.

## 2. Goals

1. Recording reliably produces valid, non-empty `mic.wav` + `system.wav`.
2. On launch, the user **chooses mic and system-audio sources and sees a live level meter** for each, so they know which device is really selected and that it hears something.
3. GUI has a **Process** button (+ pick any past recording), and after a successful run **asks whether to delete the original audio**.
4. GUI has a button to **open the recordings folder**.
5. No orphan `parec` processes, ever (crash, window close, Ctrl+C).

## 3. Target UX

```
┌ MeetNotes ──────────────────────────────────┐
│ Ready                              00:00    │
│                                             │
│ Microphone   [ Built-in Audio Analog ▾ ]    │
│              ▕██████░░░░░░░░▏  -24 dB       │
│ System audio [ Headset (BT) monitor    ▾ ]  │
│              ▕███░░░░░░░░░░░▏  -41 dB       │
│              ⚠ No signal for 5 s: muted or  │
│                wrong device?                │
│                                             │
│ [ Record ]                                  │
│ Title (optional): [_____________________]   │
│                                             │
│ [ Process last recording ] [ Recordings… ]  │
│ [ Open recordings folder ]                  │
│ [ Audio sources ] [ Settings ]              │
└─────────────────────────────────────────────┘
```

Flow:
1. Launch: both dropdowns populate, meters start immediately (live monitoring, no button needed).
2. User speaks / plays audio, sees the bars move, switches device until correct.
3. Record: Record is disabled until both devices are valid. Meters keep running during the recording as an "it's alive" indicator.
4. Stop: saves recording, status shows folder name. **No auto-processing** (see decision D1).
5. Process (last recording, or pick one from "Recordings…"): runs in a worker thread with stage status. On success, dialog: "Delete original audio (X MB)?" with **Keep** as default.
6. Open recordings folder: opens the folder in the file manager.

## 4. Design

### 4.1 Capture robustness (`capture.py`)
- `parec` writes **raw PCM** (`--raw`) to `mic.pcm` / `system.pcm`. Same format (s16le, 16 kHz, mono).
- On stop, terminate `parec` (SIGTERM is now safe), then wrap each `.pcm` into `.wav` using stdlib `wave`, then delete the `.pcm`. Output names stay `mic.wav` / `system.wav`, so pipeline/transcribe are untouched.
- Empty-recording check moves to the `.pcm` size, with a hint pointing at the device.
- `try/finally` around the whole capture: any exception, thread stop, or interpreter exit terminates both children (fixes F5).
- GUI `closeEvent` + `atexit` terminate any live children.
- Crash recovery: a folder with `*.pcm` but no `*.wav` is wrapped on demand (shown as "recoverable" in the Recordings list).
- Existing `stop_event` / main-thread-only SIGINT behavior is kept.

### 4.2 Device listing and classification (new `audio_devices.py`)
- Source of truth: `pactl --format=json list sources` (gives real description, state, mute, volume; the current `short` output has no usable description).
- Each device gets: `name`, `description`, `kind` (`input` | `monitor`), `is_default`, `muted`, `state`.
- **Mic dropdown: inputs only. System dropdown: monitors only.** This structurally removes F4.
- Defaults:
  - mic = default source if it is an input; else the first input (see D2 for BT vs laptop preference).
  - system = `<default sink>.monitor`.
- Selection persisted to `config.toml` (`mic_source`, `system_source`); `"auto"` stays valid and means "use the defaults above".
- If a saved device disappears (BT headset off), fall back to the default and show a one-line notice instead of crashing.
- Replaces `list_sources()` internals; keeps its return shape for `meetnotes sources`, which also gets the new `kind` / `[AUTO]` info.

### 4.3 Level meter (new `levels.py`)
- One small reader per device: `parec --raw` read in a worker thread, ~50 ms chunks.
- Level = peak/RMS via numpy (already installed through faster-whisper; `audioop` is gone in Python 3.13+) converted to dBFS, clamped to about -60..0 for the bar.
- Thread hands values to the GUI through a `queue.Queue` polled by a `QTimer` (same pattern as the existing result queue). **No signal handlers, no Qt calls from the worker thread.**
- Smoothing (fast attack, slow decay) so the bar is readable.
- "No signal" warning if the level stays below a floor for N seconds (default 5), with a hint (muted? wrong device?). Mute flag from `pactl` is shown too.
- Restarts cleanly on device change; stops on window close.
- Multiple `parec` clients on one source is fine on PipeWire, so meters can stay on during recording.

### 4.4 Recordings management (new `recordings.py`)
- `scan(recordings_dir)` → list of recordings: timestamp, has_mic, has_system, duration (from WAV header), size, status (`ok` | `recoverable` | `empty`).
- `last_recording()` helper for the Process-last button.
- `safe_delete(recording, recordings_dir)`: refuses anything that is not a direct child of `recordings_dir` (resolved path, no symlink escape), deletes only the known files (`mic.wav`, `system.wav`, leftover `.pcm`) then the folder if empty. Never called unless the pipeline succeeded.
- `open_folder(dir)`: creates the dir if missing, opens via `QDesktopServices.openUrl(QUrl.fromLocalFile(...))`.

### 4.5 Processing from the GUI (`gui.py`, small change to `pipeline.py`)
- Process runs `run_pipeline` in a worker thread, same queue/timer pattern.
- Add an optional `progress` callback to `run_pipeline` (default `None`, so CLI and tests are unaffected) for stage text: transcribing mic → transcribing system → summarizing → writing note.
- Success: show note filename, then the delete prompt (size shown, default **Keep**).
- Failure: show error, **no delete prompt**, audio untouched.
- Buttons are disabled while a pipeline is running; Record is disabled during processing (4 GB VRAM constraint, one model load at a time).
- Title field is used for the note title exactly as today.

### 4.6 Config
- Writes of `mic_source` / `system_source` use read-modify-write of the existing TOML dict (only the `[audio]` keys), **not** a dump of the full `Config` dataclass, so it doesn't inject defaults like `llm_model = "CHANGE_ME"` into the user's file. Comments in the file will be lost (tomli_w limitation); documented in README.

## 5. Phases (each independently shippable, one at a time)

| Phase | Scope | Files | Done when |
|-------|-------|-------|-----------|
| P1 | Capture robustness: PCM→WAV, finally-cleanup, closeEvent/atexit, recovery helper | `capture.py`, `gui.py` (closeEvent only), `tests/test_capture.py` | A GUI recording yields non-empty valid WAVs; no `parec` left after Stop/close/crash |
| P2 | Device listing + classification + mic auto-pick + `meetnotes sources` output | new `audio_devices.py`, `capture.py`, `cli.py`, `tests/test_audio_devices.py` | `sources` shows kind/default; mic can never resolve to a monitor |
| P3 | Level meter + setup panel (dropdowns, bars, no-signal warning, persistence) | new `levels.py`, `gui.py`, `config.py` (partial update), tests | Moving the mic moves the bar; chosen device is what gets recorded |
| P4 | Recordings list, Process button, delete prompt, open-folder button, `progress` callback | new `recordings.py`, `gui.py`, `pipeline.py`, tests | Record→Stop→Process→(delete?) works end to end; old recordings processable |
| P5 | Docs and polish: README GUI section, CHANGELOG, version bump to 0.2.0 | `README.md`, `CHANGELOG.md`, `pyproject.toml` | Docs match behavior |

After each phase: agent edits, **you run** `uv run pytest` and the manual check for that phase, then we move on.

## 6. Tests

Unit (no audio hardware, subprocess mocked):
- PCM→WAV wrapper: valid header, sample count matches, readable by `wave` and by `av`.
- Orphan cleanup: children terminated on exception and on `stop_event`.
- Device JSON parsing; monitor vs input classification; mic never resolves to a monitor; default fallback when the saved device is gone.
- Level math: silence, full-scale, a known sine → expected dBFS; smoothing.
- Recordings scan: ok / recoverable / empty cases; duration from header.
- `safe_delete`: refuses paths outside `recordings_dir`, symlink escapes, and non-recording files; deletes only the known files.
- Config partial update: only `[audio]` keys change; other keys preserved.

GUI (pytest-qt, `QMessageBox` and `QDesktopServices` monkeypatched):
- Record disabled until both devices valid; Process disabled while running.
- Delete prompt appears only after success, defaults to Keep, "Delete" calls `safe_delete`, "Keep" doesn't.
- Open-folder button calls `QDesktopServices.openUrl` with the recordings dir.

Manual checklist (owner):
1. Launch, move through the mic dropdown, bar reacts to your voice on the right device.
2. Play a YouTube video, system bar reacts; pause, it drops.
3. Mute the mic, the warning appears after ~5 s.
4. Record 20 s, Stop, `ls -l` shows non-zero `mic.wav` and `system.wav`; `pgrep -a parec` is empty.
5. Process, note appears in the vault, delete prompt shows, choose Keep, files remain; repeat and choose Delete, folder gone.
6. Kill the GUI mid-recording (`kill -9`): no orphan `parec` after relaunch; folder shows as recoverable.
7. Open-folder button opens the right directory.

## 7. Decisions needed from you

| ID | Question | My default |
|----|----------|------------|
| D1 | Should Stop auto-process (current behavior) or only save, with Process as a separate step? | Save only. Process is explicit. |
| D2 | Mic auto-pick when both a laptop mic and a BT headset mic exist | Laptop mic (BT HFP mic degrades headset audio quality). Always overridable in the dropdown. |
| D3 | Delete = permanent, or move to trash? | Permanent, with a clear size-labelled prompt (no new dependency). Trash is possible via `gio trash` if you prefer. |
| D4 | `keep_audio` config key: leave unused, remove, or make it skip the prompt? | Leave as is (out of scope), flag in README. |
| D5 | Keep meters running during recording? | Yes. Extra `parec` reader, cheap, confirms capture is alive. |
| D6 | Also add `--delete-audio` to the CLI `process` command? | No, GUI only for now. |

## 8. Risks

- `pactl --format=json` needs a recent pactl (fine on Ubuntu 26.04, will fall back to `short` parsing with a plain-name description otherwise).
- BT devices appearing/disappearing mid-session: handled by fallback + notice, but the dropdown won't live-refresh in v0.2 (a "Refresh" button is cheap to add in P3).
- Meter `parec` on a source that is suspended can read nothing until audio flows; the no-signal warning wording must not claim the device is broken.
- Wayland: nothing here depends on X11.
- Config writes lose TOML comments (see 4.6).

## 9. Explicitly out of scope

Window picker wiring (F8), `--no-gui` fix (F9), `keep_audio` semantics (F7), real Settings dialog, macOS/Windows capture.
