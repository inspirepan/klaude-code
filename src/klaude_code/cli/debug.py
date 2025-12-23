"""Debug utilities for CLI."""

import subprocess
import sys
from pathlib import Path

import typer

from klaude_code.trace import DebugType, log

DEBUG_FILTER_HELP = "Comma-separated debug types: " + ", ".join(dt.value for dt in DebugType)


def parse_debug_filters(raw: str | None) -> set[DebugType] | None:
    """Parse comma-separated debug filter string into a set of DebugType."""
    if raw is None:
        return None
    filters: set[DebugType] = set()
    for chunk in raw.split(","):
        normalized = chunk.strip().lower().replace("-", "_")
        if not normalized:
            continue
        try:
            filters.add(DebugType(normalized))
        except ValueError:  # pragma: no cover - user input validation
            valid_options = ", ".join(dt.value for dt in DebugType)
            log(
                (
                    f"Invalid debug filter '{normalized}'. Valid options: {valid_options}",
                    "red",
                )
            )
            raise typer.Exit(2) from None
    return filters or None


def resolve_debug_settings(flag: bool, raw_filters: str | None) -> tuple[bool, set[DebugType] | None]:
    """Resolve debug flag and filters into effective settings."""
    filters = parse_debug_filters(raw_filters)
    effective_flag = flag or (filters is not None)
    return effective_flag, filters


def open_log_file_in_editor(path: Path) -> None:
    """Open the given log file in a text editor without blocking the CLI."""

    editor = ""

    for cmd in ["code", "TextEdit", "notepad"]:
        try:
            subprocess.run(["which", cmd], check=True, capture_output=True)
            editor = cmd
            break
        except (subprocess.CalledProcessError, FileNotFoundError):
            continue

    if not editor:
        if sys.platform == "darwin":
            editor = "open"
        elif sys.platform == "win32":
            editor = "notepad"
        else:
            editor = "xdg-open"

    try:
        # Detach stdin to prevent the editor from interfering with terminal input state.
        # Without this, the spawned process inherits the parent's TTY and can disrupt
        # prompt_toolkit's keyboard handling (e.g., history navigation with up/down keys).
        subprocess.Popen(
            [editor, str(path)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        log((f"Error: Editor '{editor}' not found", "red"))
    except Exception as exc:  # pragma: no cover - best effort
        log((f"Warning: failed to open log file in editor: {exc}", "yellow"))
