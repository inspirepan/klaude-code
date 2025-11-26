from __future__ import annotations

import math
import time

from rich._spinners import SPINNERS
from rich.color import Color
from rich.console import Console, ConsoleOptions, RenderableType, RenderResult
from rich.style import Style
from rich.text import Text

from klaude_code.config import constants as config_constants
from klaude_code.ui.base.theme import ThemeKey

SPINNERS.update(
    {
        "claude": {
            "interval": 100,
            "frames": ["✶", "✻", "✽", "✻", "✶", "✳", "✢", "·", "✢", "✳"],
        },
        "copilot": {
            "interval": 100,
            "frames": ["∙", "∙", "◉", "◉", "●", "◉", "◉", "◎"],
        },
    }
)

_process_start: float | None = None


def _elapsed_since_start() -> float:
    """Return seconds elapsed since first call in this process."""
    global _process_start
    now = time.perf_counter()
    if _process_start is None:
        _process_start = now
    return now - _process_start


def _shimmer_profile(main_text: str) -> list[tuple[str, float]]:
    """Compute per-character shimmer intensity for a horizontal band.

    Returns a list of (character, intensity) where intensity is in [0, 1].
    """

    chars = list(main_text)
    if not chars:
        return []

    padding = config_constants.STATUS_SHIMMER_PADDING
    period = len(chars) + padding * 2
    sweep_seconds = config_constants.STATUS_SHIMMER_SWEEP_SECONDS
    elapsed = _elapsed_since_start()
    pos_f = (elapsed % sweep_seconds) / sweep_seconds * float(period)
    pos = int(pos_f)
    band_half_width = config_constants.STATUS_SHIMMER_BAND_HALF_WIDTH

    profile: list[tuple[str, float]] = []
    for index, ch in enumerate(chars):
        i_pos = index + padding
        dist = abs(i_pos - pos)
        if dist <= band_half_width:
            x = math.pi * (dist / band_half_width)
            intensity = 0.5 * (1.0 + math.cos(x))
        else:
            intensity = 0.0
        profile.append((ch, intensity))
    return profile


def _shimmer_style(console: Console, base_style: Style, intensity: float) -> Style:
    """Compute shimmer style for a single character.

    When intensity is 0, returns the base style. As intensity increases, the
    foreground color is blended towards the terminal background color, similar
    to codex-rs shimmer's use of default_fg/default_bg and blend().
    """

    if intensity <= 0.0:
        return base_style

    alpha = max(0.0, min(1.0, intensity * config_constants.STATUS_SHIMMER_ALPHA_SCALE))

    base_color = base_style.color or Color.default()
    base_triplet = base_color.get_truecolor()
    bg_triplet = Color.default().get_truecolor(foreground=False)

    base_r, base_g, base_b = base_triplet
    bg_r, bg_g, bg_b = bg_triplet

    r = int(bg_r * alpha + base_r * (1.0 - alpha))
    g = int(bg_g * alpha + base_g * (1.0 - alpha))
    b = int(bg_b * alpha + base_b * (1.0 - alpha))

    shimmer_color = Color.from_rgb(r, g, b)
    return base_style + Style(color=shimmer_color)


class ShimmerStatusText:
    """Renderable status line with shimmer effect on the main text."""

    def __init__(self, main_text: str, main_style: ThemeKey) -> None:
        self._main_text = main_text
        self._main_style = main_style
        self._hint_text = " (esc to interrupt)"
        self._hint_style = ThemeKey.STATUS_HINT

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        text = Text()
        base_style = console.get_style(str(self._main_style))

        for ch, intensity in _shimmer_profile(self._main_text):
            style = _shimmer_style(console, base_style, intensity)
            text.append(ch, style=style)

        text.append(self._hint_text, style=self._hint_style)
        yield text


def spinner_name() -> str:
    return "copilot"


def render_status_text(main_text: str, main_style: ThemeKey) -> RenderableType:
    """Create animated status text with shimmer main text and hint suffix."""
    return ShimmerStatusText(main_text, main_style)
