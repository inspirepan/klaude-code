"""Fold large multi-line pastes into a short marker.

prompt_toolkit already parses terminal bracketed paste mode and exposes the
pasted payload via a `<bracketed-paste>` key event.

We keep the editor buffer small by inserting a marker like:
- `[paste #3 +42 lines]`  (when many lines)
- `[paste #3 1205 chars]` (when very long)

On submit, markers are expanded back to the original pasted content.
"""

from __future__ import annotations

import re

_PASTE_MARKER_RE = re.compile(r"\[paste #(?P<id>\d+)(?: (?P<meta>\+\d+ lines|\d+ chars))?\]")


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

    def expand_markers(self, text: str) -> str:
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
            return content

        out = _PASTE_MARKER_RE.sub(_replace, text)
        for pid in used:
            self._pastes.pop(pid, None)
        return out


paste_state = PasteBufferState()


def store_paste(text: str) -> str:
    return paste_state.store(text)


def expand_paste_markers(text: str) -> str:
    return paste_state.expand_markers(text)
