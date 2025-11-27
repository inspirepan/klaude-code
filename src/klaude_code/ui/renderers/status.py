from __future__ import annotations

import math
import time

from rich._spinners import SPINNERS
from rich.color import Color
from rich.console import Console, ConsoleOptions, RenderableType, RenderResult
from rich.spinner import Spinner as RichSpinner
from rich.table import Table
from rich.style import Style
from rich.text import Text
import rich.status as rich_status

from klaude_code.config import constants as config_constants
from klaude_code.ui.base.terminal_color import get_last_terminal_background_rgb
from klaude_code.ui.base.theme import ThemeKey


BREATHING_SPINNER_NAME = "dot"

SPINNERS.update(
    {
        BREATHING_SPINNER_NAME: {
            "interval": 100,
            # Frames content is ignored by the custom breathing spinner implementation,
            # but we keep a single-frame list for correct width measurement.
            "frames": ["⏺"],
        }
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


def _breathing_intensity() -> float:
    """Compute breathing intensity in [0, 1] for the spinner.

    Intensity follows a smooth cosine curve over the configured period, starting
    from 0 (fully blended into background), rising to 1 (full style color),
    then returning to 0, giving a subtle "breathing" effect.
    """

    period = max(config_constants.SPINNER_BREATH_PERIOD_SECONDS, 0.1)
    elapsed = _elapsed_since_start()
    phase = (elapsed % period) / period
    return 0.5 * (1.0 - math.cos(2.0 * math.pi * phase))


def _breathing_style(console: Console, base_style: Style, intensity: float) -> Style:
    """Blend a base style's foreground color toward terminal background.

    When intensity is 0, the color matches the background (effectively
    "transparent"); when intensity is 1, the color is the base style color.
    """

    base_color = base_style.color or Color.default()
    base_triplet = base_color.get_truecolor()
    base_r, base_g, base_b = base_triplet

    cached_bg = get_last_terminal_background_rgb()
    if cached_bg is not None:
        bg_r, bg_g, bg_b = cached_bg
    else:
        bg_triplet = Color.default().get_truecolor(foreground=False)
        bg_r, bg_g, bg_b = bg_triplet

    intensity_clamped = max(0.0, min(1.0, intensity))
    r = int(bg_r * (1.0 - intensity_clamped) + base_r * intensity_clamped)
    g = int(bg_g * (1.0 - intensity_clamped) + base_g * intensity_clamped)
    b = int(bg_b * (1.0 - intensity_clamped) + base_b * intensity_clamped)

    breathing_color = Color.from_rgb(r, g, b)
    return base_style + Style(color=breathing_color)


class ShimmerStatusText:
    """Renderable status line with shimmer effect on the main text and hint."""

    def __init__(self, main_text: str, main_style: ThemeKey) -> None:
        self._main_text = main_text
        self._main_style = main_style
        self._hint_text = " (esc to interrupt)"
        self._hint_style = ThemeKey.STATUS_HINT

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        text = Text()
        main_style = console.get_style(str(self._main_style))
        hint_style = console.get_style(str(self._hint_style))

        combined_text = f"{self._main_text}{self._hint_text}"
        split_index = len(self._main_text)

        for index, (ch, intensity) in enumerate(_shimmer_profile(combined_text)):
            base_style = main_style if index < split_index else hint_style
            style = _shimmer_style(console, base_style, intensity)
            text.append(ch, style=style)

        yield text


def spinner_name() -> str:
    return BREATHING_SPINNER_NAME


def render_status_text(main_text: str, main_style: ThemeKey) -> RenderableType:
    """Create animated status text with shimmer main text and hint suffix."""
    return ShimmerStatusText(main_text, main_style)


class BreathingSpinner(RichSpinner):
    """Custom spinner that animates color instead of glyphs.

    The spinner always renders a single "⏺" glyph whose foreground color
    smoothly interpolates between the terminal background and the spinner
    style color, producing a breathing effect.
    """

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:  # type: ignore[override]
        if self.name != BREATHING_SPINNER_NAME:
            # Fallback to Rich's default behavior for other spinners.
            yield from super().__rich_console__(console, options)
            return

        yield self._render_breathing(console)

    def _resolve_base_style(self, console: Console) -> Style:
        style = self.style
        if isinstance(style, Style):
            return style
        if style is None:
            return Style()
        style_name = str(style).strip()
        if not style_name:
            return Style()
        return console.get_style(style_name)

    def _render_breathing(self, console: Console) -> RenderableType:
        base_style = self._resolve_base_style(console)
        intensity = _breathing_intensity()
        style = _breathing_style(console, base_style, intensity)

        glyph = self.frames[0] if self.frames else "⏺"
        frame = Text(glyph, style=style)

        if not self.text:
            return frame
        if isinstance(self.text, (str, Text)):
            return Text.assemble(frame, " ", self.text)

        table = Table.grid(padding=1)
        table.add_row(frame, self.text)
        return table


# Monkey-patch Rich's Status module to use the breathing spinner implementation
# for the configured spinner name, while preserving default behavior elsewhere.
try:
    rich_status.Spinner = BreathingSpinner  # type: ignore[assignment]
except Exception:
    # Best-effort patch; if it fails we silently fall back to default spinner.
    pass
