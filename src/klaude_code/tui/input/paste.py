"""Save large pastes to temporary files and insert short editor markers.

prompt_toolkit already parses terminal bracketed paste mode and exposes the
pasted payload via a `<bracketed-paste>` key event.

We keep the editor buffer small by inserting a marker like:
- `[paste #3 +42 lines: /path/to/paste.txt]`  (when many lines)
- `[paste #3 1205 chars: /path/to/paste.txt]` (when very long)

On submit, each marker becomes a short model-facing reference to the saved file.
"""

from __future__ import annotations

import re
import secrets
import time
from pathlib import Path

from klaude_code.prompts.attachments import PASTE_REFERENCE_TEMPLATE

_PASTE_MARKER_RE = re.compile(
    r"\[paste #(?P<id>\d+)(?: (?P<meta>\+\d+ lines|\d+ chars))?(?:: [^\]\r\n]+)?\]"
)

PASTE_FILE_THRESHOLD_LINES = 20
PASTE_FILE_THRESHOLD_CHARS = 2000
PASTE_FILE_RETENTION_SECONDS = 7 * 24 * 60 * 60


def _default_paste_dir() -> Path:
    return Path.home() / ".klaude" / "tmp"


def _prune_stale_paste_files(paste_dir: Path) -> None:
    cutoff = time.time() - PASTE_FILE_RETENTION_SECONDS
    for file_path in paste_dir.glob("paste-*.txt"):
        try:
            if file_path.stat().st_mtime < cutoff:
                file_path.unlink()
        except OSError:
            continue


def save_paste_to_file(text: str, paste_dir: Path | None = None) -> Path | None:
    """Save paste content to a file if it exceeds size thresholds.

    Returns the file path if saved, None if content is below threshold.
    """
    lines = text.splitlines()
    if len(lines) < PASTE_FILE_THRESHOLD_LINES and len(text) < PASTE_FILE_THRESHOLD_CHARS:
        return None

    paste_dir = paste_dir or _default_paste_dir()
    paste_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    _prune_stale_paste_files(paste_dir)

    file_path = paste_dir / f"paste-{secrets.token_hex(6)}.txt"
    file_path.write_text(text, encoding="utf-8")
    return file_path


class PasteBufferState:
    def __init__(self) -> None:
        self._next_id = 1
        self._paste_files: dict[int, Path] = {}

    def store(self, text: str, paste_dir: Path | None = None) -> str | None:
        file_path = save_paste_to_file(text, paste_dir)
        if file_path is None:
            return None

        paste_id = self._next_id
        self._next_id += 1

        lines = text.splitlines()
        line_count = max(1, len(lines))
        total_chars = len(text)

        resolved_path = file_path.resolve()
        if line_count >= PASTE_FILE_THRESHOLD_LINES:
            marker = f"[paste #{paste_id} +{line_count} lines: {resolved_path}]"
        else:
            marker = f"[paste #{paste_id} {total_chars} chars: {resolved_path}]"

        self._paste_files[paste_id] = resolved_path
        return marker

    def expand_markers(self, text: str, *, consume: bool = True) -> str:
        used: set[int] = set()

        def _replace(m: re.Match[str]) -> str:
            try:
                paste_id = int(m.group("id"))
            except (TypeError, ValueError):
                return m.group(0)

            file_path = self._paste_files.get(paste_id)
            if file_path is None:
                return m.group(0)

            used.add(paste_id)
            return f"\n{PASTE_REFERENCE_TEMPLATE.format(path=file_path)}\n"

        out = _PASTE_MARKER_RE.sub(_replace, text)
        if consume:
            for pid in used:
                self._paste_files.pop(pid, None)
        return out


paste_state = PasteBufferState()


def store_paste(text: str, paste_dir: Path | None = None) -> str | None:
    return paste_state.store(text, paste_dir)


def expand_paste_markers(text: str) -> str:
    return paste_state.expand_markers(text)


def expand_paste_markers_for_history(text: str) -> str:
    return paste_state.expand_markers(text, consume=False)
