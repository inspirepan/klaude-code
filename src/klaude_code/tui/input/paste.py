"""Fold large multi-line pastes into a short marker.

prompt_toolkit already parses terminal bracketed paste mode and exposes the
pasted payload via a `<bracketed-paste>` key event.

We keep the editor buffer small by inserting a marker like:
- `[paste #3 +42 lines]`  (when many lines)
- `[paste #3 1205 chars]` (when very long)

On submit, markers are expanded back to the original pasted content.
Large pastes can optionally be saved to files in the session directory.
"""

from __future__ import annotations

import re
import secrets
from pathlib import Path

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
        self._pastes: dict[int, str] = {}

    def store(self, text: str) -> str:
        paste_id = self._next_id
        self._next_id += 1

        lines = text.splitlines()
        line_count = max(1, len(lines))
        total_chars = len(text)

        if line_count > 10:
            marker = f"[paste #{paste_id} +{line_count} lines]"
        else:
            marker = f"[paste #{paste_id} {total_chars} chars]"

        self._pastes[paste_id] = text
        return marker

    def expand_markers(self, text: str, *, consume: bool = True) -> str:
        used: set[int] = set()

        def _replace(m: re.Match[str]) -> str:
            try:
                paste_id = int(m.group("id"))
            except (TypeError, ValueError):
                return m.group(0)

            content = self._pastes.get(paste_id)
            if content is None:
                return m.group(0)

            used.add(paste_id)
            return f"\n{content}\n"

        out = _PASTE_MARKER_RE.sub(_replace, text)
        if consume:
            for pid in used:
                self._pastes.pop(pid, None)
        return out

    def expand_markers_with_file_save(self, text: str, session_dir: Path) -> tuple[str, dict[str, str]]:
        """Expand paste markers, saving large pastes to files.

        Large pastes are wrapped in ``<pasteN>`` XML tags and saved to session
        directory files.  Returns (expanded_text, {tag_name: file_path}).
        """
        pasted_files: dict[str, str] = {}
        tag_counter = len(pasted_files)
        used: set[int] = set()

        def _replace(m: re.Match[str]) -> str:
            nonlocal tag_counter
            try:
                paste_id = int(m.group("id"))
            except (TypeError, ValueError):
                return m.group(0)

            content = self._pastes.get(paste_id)
            if content is None:
                return m.group(0)

            used.add(paste_id)

            file_path = save_paste_to_file(content, session_dir)
            if file_path is not None:
                tag_counter += 1
                tag = f"paste{tag_counter}"
                pasted_files[tag] = str(file_path)
                return f"\n<{tag}>\n{content}\n</{tag}>\n"

            return f"\n{content}\n"

        out = _PASTE_MARKER_RE.sub(_replace, text)
        for pid in used:
            self._pastes.pop(pid, None)
        return out, pasted_files


paste_state = PasteBufferState()


def store_paste(text: str) -> str:
    return paste_state.store(text)


def expand_paste_markers(text: str) -> str:
    return paste_state.expand_markers(text)


def expand_paste_markers_for_history(text: str) -> str:
    return paste_state.expand_markers(text, consume=False)


def expand_paste_markers_with_file_save(text: str, session_dir: Path) -> tuple[str, dict[str, str]]:
    return paste_state.expand_markers_with_file_save(text, session_dir)
