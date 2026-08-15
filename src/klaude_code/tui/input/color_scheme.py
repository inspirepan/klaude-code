"""Terminal color-scheme change reporting (DEC private mode 2031).

Terminals that implement the color-scheme reporting extension (Ghostty,
kitty, WezTerm, Contour, ...) push ``CSI ? 997 ; 1 n`` (dark) or
``CSI ? 997 ; 2 n`` (light) whenever their palette flips — e.g. when the OS
switches between dark and light appearance — once mode 2031 is enabled.

prompt_toolkit's vt100 parser does not know these reports. Its fallback
emits a bare Escape key press — which the REPL binds to "interrupt the
running task" — followed by the report body as literal text. So the
sequences are registered in ``ANSI_SEQUENCES`` mapped to ``Keys.Ignore``
(harmless even when reporting is off but a previous program leaked the
mode), and the REPL's ``Keys.Ignore`` binding inspects ``KeyPress.data`` to
turn a matching report into a theme-switch callback.

Terminals without the extension silently ignore the enable/disable writes.
"""

from __future__ import annotations

from typing import cast

from prompt_toolkit.input import ansi_escape_sequences
from prompt_toolkit.keys import Keys

COLOR_SCHEME_REPORT_ENABLE = "\x1b[?2031h"
COLOR_SCHEME_REPORT_DISABLE = "\x1b[?2031l"

_DARK_REPORT = "\x1b[?997;1n"
_LIGHT_REPORT = "\x1b[?997;2n"

_installed = False


def install_color_scheme_sequences() -> None:
    """Teach the vt100 parser the mode-2031 color-scheme reports.

    Idempotent; never overrides sequences prompt_toolkit already defines.
    """
    global _installed
    if _installed:
        return
    _installed = True
    table = cast("dict[str, object]", ansi_escape_sequences.ANSI_SEQUENCES)
    table.setdefault(_DARK_REPORT, Keys.Ignore)
    table.setdefault(_LIGHT_REPORT, Keys.Ignore)


def theme_from_key_data(data: str) -> str | None:
    """Map a ``Keys.Ignore`` press's raw sequence to ``"dark"``/``"light"``."""
    if data == _DARK_REPORT:
        return "dark"
    if data == _LIGHT_REPORT:
        return "light"
    return None
