from __future__ import annotations

import argparse
import sys
from pathlib import Path

from meetnotes.config import Config, ConfigError


def _cmd_init(args: argparse.Namespace) -> int:
    """Write default config to ~/.config/meetnotes/config.toml."""
    path = Path.home() / ".config" / "meetnotes" / "config.toml"
    if path.exists():
        print(f"Config already exists at {path}", file=sys.stderr)
        return 2
    path.parent.mkdir(parents=True, exist_ok=True)
    Config.default().save(path)

    # Add project to PYTHONPATH and aliases in ~/.bashrc (skip with --no-bashrc)
    if not args.no_bashrc:
        project_dir = Path(__file__).parent.parent.parent
        marker = "# meetnotes"
        bashrc = Path.home() / ".bashrc"
        lines = [
            "\n# meetnotes — local meeting note-taker",
            'alias meetnotes="meetnotes"',
            'alias mn="meetnotes"',
            f'export PYTHONPATH="$PYTHONPATH:{project_dir}/src"',
        ]
        try:
            content = bashrc.read_text()
            if marker not in content:
                bashrc.write_text(content + "\n".join(lines) + "\n")
        except Exception as exc:
            print(f"Could not update ~/.bashrc: {exc}", file=sys.stderr)
        else:
            print("Run: source ~/.bashrc")

    print(f"Default config written to {path}")
    return 0


def _cmd_sources(_args: argparse.Namespace) -> int:
    """List available PulseAudio/PipeWire sources."""
    from meetnotes.capture import list_sources
    try:
        sources = list_sources()
    except FileNotFoundError as exc:
        print(f"pulseaudio not found: {exc}", file=sys.stderr)
        return 2
    for src in sources:
        marker = " <-- auto" if src.get("auto") else ""
        print(f"  {src['name']}{marker}")
    return 0


def _cmd_start(args: argparse.Namespace) -> int:
    """Record and process a meeting. With --no-gui, runs headless CLI mode."""
    if not args.no_gui:
        import subprocess
        from meetnotes.gui import run_gui

        # Launch Obsidian if not already running
        obsidian_pid = subprocess.run(
            ["pgrep", "-x", "obsidian"],
            capture_output=True, text=True
        ).stdout.strip()
        if not obsidian_pid:
            subprocess.Popen(["obsidian"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            import time
            time.sleep(2)

        # Run GUI (blocks until closed)
        run_gui()
        return 0

    # CLI mode: record until Ctrl+C, then process
    import signal
    import threading
    from meetnotes.config import Config
    from meetnotes.capture import start_recording
    from meetnotes.pipeline import run_pipeline

    cfg = Config.load()
    stop_event = threading.Event()

    def _on_sigint(_sig, _frame):
        stop_event.set()
    signal.signal(signal.SIGINT, _on_sigint)

    try:
        mic, system = start_recording(cfg, stop_event)
        result = run_pipeline(mic, system, cfg, args.title, no_llm=args.no_llm)
        print(f"Note written: {result['note_path']}")
    except KeyboardInterrupt:
        print("\nRecording stopped.")
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    finally:
        signal.signal(signal.SIGINT, signal.SIG_DFL)
    return 0


def _cmd_process(args: argparse.Namespace) -> int:
    """Process existing audio files."""
    from meetnotes.pipeline import run_pipeline
    cfg = Config.load()
    mic_path = Path(args.mic)
    system_path = Path(args.system) if args.system else None
    result = run_pipeline(mic_path, system_path, cfg, args.title, no_llm=args.no_llm)
    print(f"Note written: {result['note_path']}")
    return 0


def _cmd_download_model(_args: argparse.Namespace) -> int:
    """Download the configured Whisper model."""
    from meetnotes.transcribe import download_model
    cfg = Config.load()
    download_model(cfg)
    print("Model downloaded.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="meetnotes", description="Local meeting note-taker")
    sub = parser.add_subparsers(dest="cmd", required=True)

    init_p = sub.add_parser("init", help="Write default config")
    init_p.add_argument("--no-bashrc", action="store_true", help="Skip modifying ~/.bashrc")
    sub.add_parser("sources", help="List available audio sources")
    sub.add_parser("download-model", help="Download Whisper model")

    start_p = sub.add_parser("start", help="Record and process a meeting")
    start_p.add_argument("--title", default=None)
    start_p.add_argument("--no-llm", action="store_true")
    start_p.add_argument("--no-gui", action="store_true", help="Run CLI mode without GUI")

    proc_p = sub.add_parser("process", help="Process existing audio files")
    proc_p.add_argument("mic")
    proc_p.add_argument("system", nargs="?", default=None)
    proc_p.add_argument("--title", default=None)
    proc_p.add_argument("--no-llm", action="store_true")

    args = parser.parse_args(argv)

    # Validate config exists for commands that need it
    if args.cmd in ("start", "process", "download-model"):
        try:
            Config.load()
        except ConfigError as exc:
            print(f"Config error: {exc}", file=sys.stderr)
            return 2

    dispatch = {
        "init": _cmd_init,
        "sources": _cmd_sources,
        "start": _cmd_start,
        "process": _cmd_process,
        "download-model": _cmd_download_model,
    }
    return dispatch[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
