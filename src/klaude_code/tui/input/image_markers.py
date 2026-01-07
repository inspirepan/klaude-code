"""Image marker syntax for REPL input.

We use a stable, history-friendly marker in the text buffer:

    [image <path>]

`<path>` can be either unquoted (no whitespace) or double-quoted.
This allows input history to be replayed to re-attach images.
"""

from __future__ import annotations

import re

IMAGE_MARKER_RE = re.compile(r'\[image (?P<path>"[^"]+"|[^\]]+)\]')


def format_image_marker(path: str) -> str:
    path_str = path.strip()
    if any(ch.isspace() for ch in path_str):
        return f'[image "{path_str}"]'
    return f"[image {path_str}]"


def parse_image_marker_path(raw: str) -> str:
    s = raw.strip()
    if len(s) >= 2 and s.startswith('"') and s.endswith('"'):
        return s[1:-1]
    return s
