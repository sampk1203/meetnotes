# meetnotes: local meeting note-taker

Read AI-style notes, but the audio and transcription stay on this machine.
Record a call (mic + system audio) -> transcribe on GPU -> summarize via LLM API -> write markdown to an Obsidian vault.

Target platforms: **Linux only** (Ubuntu 26.04, PipeWire/pipewire-pulse). NVIDIA RTX 3050 4 GB VRAM laptop. Python >= 3.11, `uv` project, src layout, package name `meetnotes`, console script `meetnotes`.

GUI: dark-mode desktop app (PyQt6) with window-picker overlay for selecting which application window to focus audio capture on. Audio capture is OS-level (mic + full system output via pipewire-pulse), not app-specific — window picker is metadata only (tags the recording session for naming/context).

---

## Agent workflow (follow strictly)

- **One phase at a time.** Finish a phase, stop, and summarize. Do not start the next phase unprompted.
- Agent edits files. **Owner runs tests / the tool.** Do not run recordings or model downloads yourself.
- Surgical edits over rewrites once code exists.
- Add tests for every module (pytest). Update `README.md` and `CHANGELOG.md` each phase.
- Present only the files you created or edited.
- Terse commit-style notes. No filler.

## Hard constraints

- 4 GB VRAM: Whisper and any local model never share the GPU. Whisper is loaded, used, then released (`del model; gc.collect()`) before anything else.
- Home internet is limited. Models download once via an explicit `meetnotes download-model` command. After that the tool must run fully offline except for the LLM API call.
- No secrets in files. The API key is read from an env var whose *name* is set in config.
- Transcript text is sent to the configured LLM endpoint. State this plainly in the README. Provide `--no-llm` to skip it and only produce the transcript note.
- Never overwrite an existing note. Add a numeric suffix instead.
- **All platforms**: audio capture must be at the OS level (so the full system output + mic are captured), not app-specific.

---

## Stack

- Python >= 3.11, `uv` project, src layout, package name `meetnotes`.
- Deps (keep minimal): `faster-whisper`, `openai` (client only, used against any OpenAI-compatible `base_url`), `PyQt6` (GUI), stdlib `tomllib`, `argparse`, `subprocess`. Dev: `pytest`.
- System tools used via subprocess: `pactl`, `parec` (works on PipeWire through pipewire-pulse). Check they exist at startup and give a clear error if not.

---

## Config (`~/.config/meetnotes/config.toml`)

Created with defaults by `meetnotes init`.

```toml
[vault]
path = "~/Documents/Obsidian"        # vault root
folder = "Meetings"                  # subfolder for notes

[audio]
mic_source = "auto"                  # "auto" = default source, or a device name
system_source = "auto"               # "auto" = system output monitor/loopback
keep_audio = false                   # delete wavs after a successful run
recordings_dir = "~/.local/share/meetnotes/recordings"

[whisper]
model = "large-v3-turbo"             # fallback to "small" if VRAM is tight
device = "auto"                      # auto | cuda | cpu
compute_type = "auto"                # auto: int8_float16 on cuda, int8 on cpu
language = "auto"
vad_filter = true

[llm]
base_url = "http://localhost:11434/v1"   # any OpenAI-compatible endpoint
api_key_env = "MEETNOTES_API_KEY"
model = "CHANGE_ME"
chunk_chars = 12000

[gui]
theme = "dark"
window_picker_timeout = 15         # seconds to pick a window
```

---

## Pipeline

### 1. Capture (`capture.py`)

Cross-platform audio capture abstraction:

- **Linux**: fall back to `pactl`/`parec` subprocess (PipeWire/pulseaudio). Source discovery via `pactl get-default-source`, `pactl get-default-sink`, `pactl list short sources`.
- **Windows**: `sounddevice` with WASAPI loopback device. Enumerate via `sounddevice.list_devices()`.
- **macOS**: `sounddevice` with Core Audio. Enumerate similarly.

Recording parameters: 16 kHz mono WAV (`format=s16le`, `rate=16000`, `channels=1`).

`start` records until Ctrl+C (SIGINT) or GUI stop button, shuts down processes/devices cleanly so WAV headers are finalised. A single stop signal ends both tracks.

Output: `<recordings_dir>/<YYYY-MM-DD_HHMM>/mic.wav` and `system.wav`.

**Window picker (GUI only):** After pressing "Record" in the GUI, show an overlay cursor that lets the user click on a window to tag it as the "focus" of the session (for later metadata/naming). Audio capture is always OS-level (mic + full system output) regardless.

Bluetooth/earphone switching mid-call changes the sink — document as a known limitation.

### 2. Transcribe (`transcribe.py`)

- Transcribe each track separately with `faster-whisper` (VAD on, word timestamps off).
- Label segments `Me` (mic track) and `Others` (system track). Merge by start time into one ordered list.
- Resolve `device`/`compute_type` from `auto` (CUDA available -> `cuda` + `int8_float16`, else `cpu` + `int8`).
- Release the model before returning.
- If the mic and system tracks contain the same speech (speaker bleed), do not try to dedupe in v1.

### 3. Summarize (`summarize.py`)

- Skipped when `--no-llm`.
- Split the labelled transcript into chunks of about `chunk_chars` on segment boundaries. Summarize each chunk, then merge the chunk summaries in a final call (map-reduce). Single call if the transcript fits in one chunk.
- Ask for structured markdown: **Summary**, **Decisions**, **Action items** (as `- [ ]` checkboxes, owner if stated), **Open questions**, plus a short title.
- Retry with exponential backoff on transient errors (3 tries). On final failure, still write the transcript note and exit non-zero with a clear message.

### 4. Write to Obsidian (`vault.py`)

- Files in `<vault>/<folder>/`:
  - `YYYY-MM-DD HHMM - <Title>.md` (the notes)
  - `YYYY-MM-DD HHMM - <Title> - transcript.md` (full labelled transcript)
- Notes file has YAML frontmatter: `date`, `duration`, `type: meeting`, `tags: [meeting]`, `source: meetnotes`. Body is the structured summary, then a `[[... - transcript]]` link.
- Sanitise the title for filenames. Write atomically (temp file, then rename).

### 5. CLI (`cli.py`)

- `meetnotes init`: write default config.
- `meetnotes sources`: list available audio sources per platform and show which are auto-selected.
- `meetnotes download-model`: fetch the configured Whisper model once into the cache.
- `meetnotes start [--title T] [--no-llm]`: record until Ctrl+C (CLI) or stop button (GUI), then run the whole pipeline.
- `meetnotes process <mic.wav> [<system.wav>] [--title T] [--no-llm]`: run the pipeline on existing audio. A single file is treated as one track labelled `Speaker`.
- Exit codes: 0 ok, 1 pipeline error, 2 usage/config error.

### 6. GUI (`gui.py`) — PyQt6, dark mode

- Main window: "Record" / "Stop" button, current status, recording timer, save-to path display.
- "Sources" button opens a dialog to choose mic and system audio devices.
- "Settings" button opens a dialog bound to `~/.config/meetnotes/config.toml`.
- Window picker: clicking "Pick Window" starts a cross-platform window enumerator (Linux: `xdotool search`, Windows: `ctypes` Win32 `EnumWindows`, macOS: ` Quartz.CGWindowListCopyWindowInfo`); user clicks a window to tag it.
- Dark mode theme applied globally via `QApplication.setStyle("Fusion")` + custom palette (no `native` style for consistency).
- The GUI wraps the CLI pipeline — internally calls `meetnotes start --no-llm` and then runs the post-capture steps programmatically.

---

## Phases (stop after each)

1. **Skeleton + config + vault writer + CLI.** Project scaffold, `init`, `sources`, config loading, `vault.py`, `capture.py` (Linux pactl/parec stub), `cli.py`, tests, README, CHANGELOG.
2. **Transcribe.** `download-model`, `process` with `--no-llm`, track labelling and merge, device auto-resolution, tests (fake the model).
3. **Summarize.** Chunking, map-reduce, retries, tests (fake the LLM client).
4. **Capture.** `start`, clean shutdown, source discovery, tests (fake subprocess), README section on audio routing and limitations.
5. **GUI.** Dark-mode PyQt6 app, window picker, wiring to the CLI pipeline.
6. **Polish.** Error messages, `keep_audio`, install via `uv tool install .`.

---

## Tests (owner runs)

- `config`: defaults, overrides, missing/invalid values.
- `vault`: filename sanitising, no-overwrite suffixing, frontmatter, atomic write.
- `transcribe`: auto device resolution, merge ordering of two tracks (fake model).
- `summarize`: chunk boundaries, single vs map-reduce path, retry/backoff, failure still yields a transcript note (fake client).
- `capture`: source discovery parsing, argument construction, clean shutdown (fake subprocess).
- `cli`: exit codes, `--no-llm` never calls the LLM.
- `gui`: dark-mode palette application, window picker launch, record/stop toggling.

---

## Out of scope for v1

Live (streaming) transcription, speaker diarization beyond Me/Others, auto-detecting calls, speaker-bleed dedupe, Windows/macOS.

---

## Open items for the owner (decide in the phase summary if not answered)

- Default LLM `model` name and endpoint (owner's existing LLM API).
- Whether to keep a `small` Whisper fallback preset if `large-v3-turbo` is too tight on 4 GB.
- GUI icon asset (can use a placeholder SVG).
