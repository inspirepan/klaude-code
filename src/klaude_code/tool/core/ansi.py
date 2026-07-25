"""ANSI / terminal control sequence stripping for captured command output."""

from __future__ import annotations

import re

# Regex to strip ANSI and terminal control sequences from command output
#
# This is intentionally broader than just SGR color codes (e.g. "\x1b[31m").
# Many interactive or TUI-style programs emit additional escape sequences
# that move the cursor, clear the screen, or switch screen buffers
# (CSI/OSC/DCS/APC/PM, etc). If these reach the Rich console, they can
# corrupt the REPL layout. We therefore remove all of them before
# rendering the output.
ANSI_ESCAPE_RE = re.compile(
    r"""
    \x1B
    (?:
        \[[0-?]*[ -/]*[@-~]         |  # CSI sequences
        \][0-?]*.*?(?:\x07|\x1B\\) |  # OSC sequences
        P.*?(?:\x07|\x1B\\)       |  # DCS sequences
        _.*?(?:\x07|\x1B\\)       |  # APC sequences
        \^.*?(?:\x07|\x1B\\)      |  # PM sequences
        [@-Z\\-_]                      # 2-char sequences
    )
    """,
    re.VERBOSE | re.DOTALL,
)


def strip_ansi(text: str) -> str:
    """Remove ANSI/terminal control sequences from `text`."""
    return ANSI_ESCAPE_RE.sub("", text)
