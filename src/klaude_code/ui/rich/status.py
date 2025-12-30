from __future__ import annotations

import contextlib
import math
import random
import time
from collections.abc import Callable

import rich.status as rich_status
from rich.cells import cell_len
from rich.color import Color
from rich.console import Console, ConsoleOptions, RenderableType, RenderResult
from rich.measure import Measurement
from rich.spinner import Spinner as RichSpinner
from rich.style import Style
from rich.table import Table
from rich.text import Text

from klaude_code import const
from klaude_code.ui.rich.theme import ThemeKey
from klaude_code.ui.terminal.color import get_last_terminal_background_rgb

# Use an existing Rich spinner name; BreathingSpinner overrides its rendering
BREATHING_SPINNER_NAME = "dots"

# Alternating glyphs for the breathing spinner - switches at each "transparent" point
_BREATHING_SPINNER_GLYPHS_BASE = [
    "✦",
]

# Shuffle glyphs on module load for variety across sessions
BREATHING_SPINNER_GLYPHS = _BREATHING_SPINNER_GLYPHS_BASE.copy()
random.shuffle(BREATHING_SPINNER_GLYPHS)


_process_start: float | None = None
_task_start: float | None = None


def _elapsed_since_start() -> float:
    """Return seconds elapsed since first call in this process."""
    global _process_start
    now = time.perf_counter()
    if _process_start is None:
        _process_start = now
    return now - _process_start


def set_task_start(start: float | None = None) -> None:
    """Set the current task start time (perf_counter seconds)."""

    global _task_start
    _task_start = time.perf_counter() if start is None else start


def clear_task_start() -> None:
    """Clear the current task start time."""

    global _task_start
    _task_start = None


def _task_elapsed_seconds(now: float | None = None) -> float | None:
    if _task_start is None:
        return None
    current = time.perf_counter() if now is None else now
    return max(0.0, current - _task_start)


def _format_elapsed_compact(seconds: float) -> str:
    total_seconds = max(0, int(seconds))
    if total_seconds < 60:
        return f"{total_seconds}s"

    minutes, sec = divmod(total_seconds, 60)
    if minutes < 60:
        return f"{minutes}m{sec:02d}s"

    hours, minute = divmod(minutes, 60)
    return f"{hours}h{minute:02d}m{sec:02d}s"


def current_hint_text(*, min_time_width: int = 0) -> str:
    """Return the full hint string shown on the status line.

    The hint is the constant suffix shown after the main status text.

    The elapsed task time is rendered on the right side of the status line
    (near context usage), not inside the hint.
    """

    # Keep the signature stable; min_time_width is intentionally ignored.
    _ = min_time_width
    return const.STATUS_HINT_TEXT


def current_elapsed_text(*, min_time_width: int = 0) -> str | None:
    """Return the current task elapsed time text (e.g. "11s", "1m02s")."""

    elapsed = _task_elapsed_seconds()
    if elapsed is None:
        return None
    time_text = _format_elapsed_compact(elapsed)
    if min_time_width > 0:
        time_text = time_text.rjust(min_time_width)
    return time_text


class DynamicText:
    """Renderable that materializes a Text instance at render time.

    This is useful for status line elements that should refresh without
    requiring explicit spinner_update calls (e.g. elapsed time).
    """

    def __init__(
        self,
        factory: Callable[[], Text],
        *,
        min_width_cells: int = 0,
    ) -> None:
        self._factory = factory
        self.min_width_cells = min_width_cells

    @property
    def plain(self) -> str:
        return self._factory().plain

    def __rich_measure__(self, console: Console, options: ConsoleOptions) -> Measurement:
        # Ensure Table/grid layout allocates a stable width for this renderable.
        text = self._factory()
        measured = Measurement.get(console, options, text)
        min_width = max(measured.minimum, self.min_width_cells)
        max_width = max(measured.maximum, self.min_width_cells)

        limit = getattr(options, "max_width", options.size.width)
        max_width = min(max_width, limit)
        min_width = min(min_width, max_width)
        return Measurement(min_width, max_width)

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        yield self._factory()


def _shimmer_profile(main_text: str) -> list[tuple[str, float]]:
    """Compute per-character shimmer intensity for a horizontal band.

    Returns a list of (character, intensity) where intensity is in [0, 1].
    """

    chars = list(main_text)
    if not chars:
        return []

    padding = const.STATUS_SHIMMER_PADDING
    char_count = len(chars)
    period = char_count + padding * 2

    # Use same period as breathing spinner for visual consistency
    sweep_seconds = max(const.SPINNER_BREATH_PERIOD_SECONDS, 0.1)

    elapsed = _elapsed_since_start()
    # Complete one full sweep in sweep_seconds, regardless of text length
    pos_f = (elapsed / sweep_seconds % 1.0) * period
    pos = int(pos_f)
    band_half_width = const.STATUS_SHIMMER_BAND_HALF_WIDTH

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

    alpha = max(0.0, min(1.0, intensity * const.STATUS_SHIMMER_ALPHA_SCALE))

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

    period = max(const.SPINNER_BREATH_PERIOD_SECONDS, 0.1)
    elapsed = _elapsed_since_start()
    phase = (elapsed % period) / period
    return 0.5 * (1.0 - math.cos(2.0 * math.pi * phase))


def _breathing_glyph() -> str:
    """Get the current glyph for the breathing spinner.

    Alternates between glyphs at each breath cycle (when intensity reaches 0).
    """
    period = max(const.SPINNER_BREATH_PERIOD_SECONDS, 0.1)
    elapsed = _elapsed_since_start()
    cycle = int(elapsed / period)
    return BREATHING_SPINNER_GLYPHS[cycle % len(BREATHING_SPINNER_GLYPHS)]


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
    """Renderable status line with shimmer effect on the main text and hint.

    Supports optional right-aligned text that stays fixed at the right edge.
    """

    def __init__(
        self,
        main_text: str | Text,
        right_text: RenderableType | None = None,
        main_style: ThemeKey = ThemeKey.STATUS_TEXT,
    ) -> None:
        if isinstance(main_text, Text):
            text = main_text.copy()
            if not text.style:
                text.style = str(main_style)
            self._main_text = text
        else:
            self._main_text = Text(main_text, style=main_style)
        self._hint_style = ThemeKey.STATUS_HINT
        self._right_text = right_text

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        left_text = _StatusLeftText(main=self._main_text, hint_style=self._hint_style)

        if self._right_text is None:
            yield left_text
            return

        # Use Table.grid to create left-right aligned layout with a stable gap.
        table = Table.grid(expand=True, padding=(0, 1, 0, 0), collapse_padding=True, pad_edge=False)
        table.add_column(justify="left", ratio=1)
        table.add_column(justify="right")
        table.add_row(left_text, self._right_text)
        yield table


class _StatusLeftText:
    def __init__(self, *, main: Text, hint_style: ThemeKey) -> None:
        self._main = main
        self._hint_style = hint_style

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        max_width = getattr(options, "max_width", options.size.width)

        # Keep the hint visually attached to the status text, while truncating only
        # the main status segment when space is tight.
        hint_text = Text(current_hint_text().strip("\n"), style=console.get_style(str(self._hint_style)))
        hint_cells = cell_len(hint_text.plain)

        main_text = Text()
        for index, (ch, intensity) in enumerate(_shimmer_profile(self._main.plain)):
            base_style = self._main.get_style_at_offset(console, index)
            style = _shimmer_style(console, base_style, intensity)
            main_text.append(ch, style=style)

        # If the hint itself can't fit, fall back to truncating the combined text.
        if max_width <= hint_cells:
            combined = Text.assemble(main_text, hint_text)
            combined.truncate(max(1, max_width), overflow="ellipsis", pad=False)
            yield combined
            return

        main_budget = max_width - hint_cells
        main_text.truncate(max(1, main_budget), overflow="ellipsis", pad=False)
        yield Text.assemble(main_text, hint_text)


def spinner_name() -> str:
    return BREATHING_SPINNER_NAME


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

        glyph = _breathing_glyph()
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
# Best-effort patch; if it fails we silently fall back to default spinner.
with contextlib.suppress(Exception):
    rich_status.Spinner = BreathingSpinner  # type: ignore[assignment]
