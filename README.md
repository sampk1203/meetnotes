# meetnotes

Local meeting note-taker. Record calls (mic + system audio) → transcribe on GPU → summarize via LLM API → write markdown to Obsidian vault.

## Quick Start

```bash
# Install
uv tool install .

# Initialize config
meetnotes init

# Check audio sources
meetnotes sources

# Download Whisper model (one-time)
meetnotes download-model

# Record and process (CLI mode)
meetnotes start --title "My Meeting"

# Or use the GUI
python -m meetnotes.gui
```

## Audio Capture

- **Linux**: Uses `pactl`/`parec` (PipeWire/pulseaudio). OS-level capture captures all system audio + mic.
- Window picker in GUI tags which app window is the "focus" — metadata only, doesn't affect audio routing.
- Bluetooth/earphone switching mid-call changes the sink — documented limitation.

## Configuration

`~/.config/meetnotes/config.toml`:

```toml
[vault]
path = "~/Documents/Obsidian"
folder = "Meetings"

[audio]
mic_source = "auto"
system_source = "auto"
keep_audio = false
recordings_dir = "~/.local/share/meetnotes/recordings"

[whisper]
model = "large-v3-turbo"
device = "auto"
compute_type = "auto"

[llm]
base_url = "http://localhost:11434/v1"
api_key_env = "MEETNOTES_API_KEY"
model = "CHANGE_ME"
chunk_chars = 12000
```

## CLI Commands

- `meetnotes init` — Write default config
- `meetnotes sources` — List available audio sources
- `meetnotes download-model` — Download Whisper model
- `meetnotes start [--title T] [--no-llm]` — Record until Ctrl+C, then process
- `meetnotes process <mic.wav> [system.wav] [--title T] [--no-llm]` — Process existing audio

## GUI

Dark-mode desktop app with:
- Record/Stop button with timer
- Audio source selection dialog
- Window picker for session metadata
- Settings dialog

Launch: `python -m meetnotes.gui`

## Pipeline

1. **Capture**: Parallel `parec` processes for mic + system audio (16kHz mono WAV)
2. **Transcribe**: faster-whisper with VAD, label segments as "Me"/"Others", merge by time
3. **Summarize**: Map-reduce chunking via OpenAI-compatible LLM API
4. **Vault**: Write to Obsidian with frontmatter + transcript link

## Constraints

- **4 GB VRAM**: Whisper loads, runs, then releases (`del model; gc.collect()`) before next operation
- **Offline-first**: Models downloaded once, runs fully offline except LLM API call
- **No secrets in files**: API key from env var
- **Never overwrite**: Existing notes get numeric suffix

## Limitations

- Linux only
- Speaker bleed (mic + system same audio) not deduplicated
- No live/streaming transcription
- No automatic call detection

## Development

```bash
uv sync
uv run pytest tests/
```
