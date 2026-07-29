"""Save large pastes to session files and insert short editor markers.

prompt_toolkit already parses terminal bracketed paste mode and exposes the
pasted payload via a `<bracketed-paste>` key event.

We keep the editor buffer small by inserting a marker like:
- `[paste #3 +42 lines]`  (when many lines)
- `[paste #3 1205 chars]` (when very long)

On submit, each marker becomes a short model-facing reference to the saved file.
"""

from __future__ import annotations

import re
import secrets
from pathlib import Path

from klaude_code.prompts.attachments import PASTE_REFERENCE_TEMPLATE

_PASTE_MARKER_RE = re.compile(r"\[paste #(?P<id>\d+)(?: (?P<meta>\+\d+ lines|\d+ chars))?\]")

PASTE_FILE_THRESHOLD_LINES = 20
PASTE_FILE_THRESHOLD_CHARS = 2000


def save_paste_to_file(text: str, session_dir: Path) -> Path | None:
    """Save paste content to a file if it exceeds size thresholds.

    Returns the file path if saved, None if content is below threshold.
    """
    lines = text.splitlines()
    if len(lines) < PASTE_FILE_THRESHOLD_LINES and len(text) < PASTE_FILE_THRESHOLD_CHARS:
        return None

    paste_dir = session_dir / "paste-files"
    paste_dir.mkdir(parents=True, exist_ok=True)

    file_path = paste_dir / f"paste-{secrets.token_hex(6)}.txt"
    file_path.write_text(text, encoding="utf-8")
    return file_path


class PasteBufferState:
    def __init__(self) -> None:
        self._next_id = 1
        self._paste_files: dict[int, Path] = {}

    def store(self, text: str, session_dir: Path) -> str | None:
        file_path = save_paste_to_file(text, session_dir)
        if file_path is None:
            return None

        paste_id = self._next_id
        self._next_id += 1

        lines = text.splitlines()
        line_count = max(1, len(lines))
        total_chars = len(text)

        if line_count >= PASTE_FILE_THRESHOLD_LINES:
            marker = f"[paste #{paste_id} +{line_count} lines]"
        else:
            marker = f"[paste #{paste_id} {total_chars} chars]"

        self._paste_files[paste_id] = file_path.resolve()
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


def store_paste(text: str, session_dir: Path) -> str | None:
    return paste_state.store(text, session_dir)


def expand_paste_markers(text: str) -> str:
    return paste_state.expand_markers(text)


def expand_paste_markers_for_history(text: str) -> str:
    return paste_state.expand_markers(text, consume=False)
