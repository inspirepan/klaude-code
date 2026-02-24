from __future__ import annotations

import contextlib
import math
import time
from collections.abc import Callable

import rich.status as rich_status
from rich.cells import cell_len
from rich.color import Color
from rich.console import Console, ConsoleOptions, Group, RenderableType, RenderResult
from rich.measure import Measurement
from rich.spinner import Spinner as RichSpinner
from rich.style import Style
from rich.text import Text

from klaude_code.const import (
    SPINNER_BREATH_PERIOD_SECONDS,
    STATUS_HINT_TEXT,
    STATUS_SHIMMER_ALPHA_SCALE,
    STATUS_SHIMMER_BAND_HALF_WIDTH,
    STATUS_SHIMMER_ENABLED,
    STATUS_SHIMMER_PADDING,
)
from klaude_code.tui.components.common import format_elapsed_compact
from klaude_code.tui.components.rich.theme import ThemeKey

# Use an existing Rich spinner name; BreathingSpinner overrides its rendering
BREATHING_SPINNER_NAME = "dots"


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


def current_hint_text(*, min_time_width: int = 0) -> str:
    """Return the hint string shown on status metadata line.

    The elapsed task time is rendered in metadata text (when available), not
    inside the hint.
    """

    # Keep the signature stable; min_time_width is intentionally ignored.
    _ = min_time_width
    return STATUS_HINT_TEXT


def current_elapsed_text(*, min_time_width: int = 0) -> str | None:
    """Return the current task elapsed time text (e.g. "11s", "1m02s")."""

    elapsed = _task_elapsed_seconds()
    if elapsed is None:
        return None
    time_text = format_elapsed_compact(elapsed)
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


class ResponsiveDynamicText(DynamicText):
    def __init__(
        self,
        factory: Callable[[], Text],
        compact_factory: Callable[[], Text],
        *,
        min_width_cells: int = 0,
    ) -> None:
        super().__init__(factory, min_width_cells=min_width_cells)
        self._compact_factory = compact_factory

    def render(self, *, compact: bool) -> Text:
        if compact:
            return self._compact_factory()
        return self._factory()


def _shimmer_profile(main_text: str) -> list[tuple[str, float]]:
    """Compute per-character shimmer intensity for a horizontal band.

    Returns a list of (character, intensity) where intensity is in [0, 1].
    """

    chars = list(main_text)
    if not chars:
        return []

    if not STATUS_SHIMMER_ENABLED:
        return [(ch, 0.0) for ch in chars]

    padding = STATUS_SHIMMER_PADDING
    char_count = len(chars)
    period = char_count + padding * 2

    # Use same period as breathing spinner for visual consistency
    sweep_seconds = max(SPINNER_BREATH_PERIOD_SECONDS, 0.1)

    elapsed = _elapsed_since_start()
    # Complete one full sweep in sweep_seconds, regardless of text length
    pos_f = (elapsed / sweep_seconds % 1.0) * period
    pos = int(pos_f)
    band_half_width = STATUS_SHIMMER_BAND_HALF_WIDTH

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

    alpha = max(0.0, min(1.0, intensity * STATUS_SHIMMER_ALPHA_SCALE))

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


def truncate_left(text: Text, max_cells: int, *, console: Console, ellipsis: str = "…") -> Text:
    """Left-truncate Text to fit within max_cells.

    Keeps the rightmost part of the text and prepends an ellipsis when truncation occurs.
    Uses cell width so wide characters are handled reasonably.
    """

    max_cells = max(0, int(max_cells))
    if max_cells == 0:
        return Text("")

    if cell_len(text.plain) <= max_cells:
        return text

    ellipsis_cells = cell_len(ellipsis) + 1  # +1 for trailing space
    if max_cells <= ellipsis_cells:
        # Not enough space to show any meaningful suffix.
        clipped = Text(ellipsis, style=text.style)
        clipped.truncate(max_cells, overflow="crop", pad=False)
        return clipped

    suffix_budget = max_cells - ellipsis_cells
    plain = text.plain

    suffix_cells = 0
    start_index = len(plain)
    for i in range(len(plain) - 1, -1, -1):
        ch_cells = cell_len(plain[i])
        if suffix_cells + ch_cells > suffix_budget:
            break
        suffix_cells += ch_cells
        start_index = i
        if suffix_cells == suffix_budget:
            break

    if start_index >= len(plain):
        return Text(ellipsis, style=text.style)

    suffix = text[start_index:]
    try:
        ellipsis_style = suffix.get_style_at_offset(console, 0)
    except Exception:
        ellipsis_style = suffix.style or text.style

    return Text.assemble(Text(ellipsis + " ", style=ellipsis_style), suffix)


def truncate_status(text: Text, max_cells: int, *, console: Console, ellipsis: str = "…") -> Text:
    """Smart truncate Text to fit within max_cells.

    If the text contains ' | ', it right-truncates the part before ' | '
    while keeping the part after ' | ' intact.
    Otherwise, it falls back to left-truncating the entire text.
    """
    max_cells = max(0, int(max_cells))
    if max_cells == 0:
        return Text("")

    if cell_len(text.plain) <= max_cells:
        return text

    idx = text.plain.rfind(" | ")
    if idx != -1:
        left_part = text[:idx]
        right_part = text[idx:]

        right_cells = cell_len(right_part.plain)

        if right_cells + cell_len(ellipsis) <= max_cells:
            left_budget = max_cells - right_cells
            ellipsis_cells = cell_len(ellipsis)

            if left_budget <= ellipsis_cells:
                clipped_left = Text(ellipsis, style=left_part.style or text.style)
                clipped_left.truncate(left_budget, overflow="crop", pad=False)
                return Text.assemble(clipped_left, right_part)

            prefix_budget = left_budget - ellipsis_cells
            prefix_cells = 0
            end_index = 0
            plain_left = left_part.plain
            for i in range(len(plain_left)):
                ch_cells = cell_len(plain_left[i])
                if prefix_cells + ch_cells > prefix_budget:
                    break
                prefix_cells += ch_cells
                end_index = i + 1

            prefix = left_part[:end_index]
            try:
                ellipsis_style = prefix.get_style_at_offset(console, max(0, end_index - 1))
            except Exception:
                ellipsis_style = prefix.style or text.style

            return Text.assemble(prefix, Text(ellipsis, style=ellipsis_style), right_part)

    return truncate_left(text, max_cells, console=console, ellipsis=ellipsis)


class StackedStatusText:
    """Renderable [todo, status..., metadata] with shimmer on todo/status lines."""

    def __init__(
        self,
        todo_text: str | Text,
        metadata_text: RenderableType | None = None,
        status_lines: tuple[RenderableType, ...] = (),
        leading_blank_line: bool = False,
        main_style: ThemeKey = ThemeKey.STATUS_TEXT,
    ) -> None:
        if isinstance(todo_text, Text):
            text = todo_text.copy()
            if not text.style:
                text.style = str(main_style)
            self._todo_text = text
        else:
            self._todo_text = Text(todo_text, style=main_style)
        self._hint_style = ThemeKey.STATUS_HINT
        self._metadata_text = metadata_text
        self._status_lines = status_lines
        self._leading_blank_line = leading_blank_line

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        max_width = max(1, getattr(options, "max_width", options.size.width))
        line_options = options.update(no_wrap=True, overflow="ellipsis", height=1)

        todo_line = _render_single_line_text(
            _StatusShimmerLine(main=self._todo_text),
            console=console,
            options=line_options.update(max_width=max_width),
        )

        rendered_status_lines: list[Text] = []
        for status_line in self._status_lines:
            line = _render_single_line_text(
                status_line,
                console=console,
                options=line_options.update(max_width=max_width),
            )
            line = _render_single_line_text(
                _StatusShimmerLine(main=line),
                console=console,
                options=line_options.update(max_width=max_width),
            )
            if line.plain:
                rendered_status_lines.append(line)

        metadata_line = _build_metadata_line(
            metadata_text=self._metadata_text,
            hint_style=self._hint_style,
            max_width=max_width,
            console=console,
            line_options=line_options,
        )

        lines: list[Text] = []
        if self._leading_blank_line and rendered_status_lines:
            lines.append(Text(""))
        lines.extend(rendered_status_lines)
        if todo_line.plain:
            lines.append(todo_line)
        lines.append(metadata_line)

        if len(lines) == 1:
            yield lines[0]
        else:
            yield Group(*lines)


def _render_single_line_text(renderable: RenderableType, *, console: Console, options: ConsoleOptions) -> Text:
    lines = console.render_lines(renderable, options, pad=False)
    if not lines:
        return Text("")

    text = Text()
    for segment in lines[0]:
        if segment.control:
            continue
        if segment.text:
            text.append(segment.text, style=segment.style)
    return text


def _render_right_text(
    renderable: RenderableType,
    *,
    console: Console,
    options: ConsoleOptions,
    compact: bool,
) -> Text:
    if isinstance(renderable, ResponsiveDynamicText):
        return renderable.render(compact=compact)
    return _render_single_line_text(renderable, console=console, options=options)


def _build_metadata_line(
    *,
    metadata_text: RenderableType | None,
    hint_style: ThemeKey,
    max_width: int,
    console: Console,
    line_options: ConsoleOptions,
) -> Text:
    hint_text = Text(current_hint_text().strip(), style=console.get_style(str(hint_style)))
    if metadata_text is None:
        return truncate_left(hint_text, max(1, max_width), console=console)

    full_metadata_text = _render_right_text(metadata_text, console=console, options=line_options, compact=False)
    if cell_len(full_metadata_text.plain) == 0:
        return truncate_left(hint_text, max(1, max_width), console=console)

    compact_trigger_width = max(1, max_width - 4)
    compact_metadata_text: Text | None = None
    metadata_line = full_metadata_text
    if cell_len(full_metadata_text.plain) > compact_trigger_width:
        compact_metadata_text = _render_right_text(metadata_text, console=console, options=line_options, compact=True)
        if 0 < cell_len(compact_metadata_text.plain) < cell_len(full_metadata_text.plain):
            metadata_line = compact_metadata_text

    separator = Text(" · ", style=ThemeKey.STATUS_HINT)
    with_hint = Text.assemble(metadata_line, separator, hint_text)
    if cell_len(with_hint.plain) <= max_width:
        return with_hint
    if cell_len(metadata_line.plain) <= max_width:
        return metadata_line

    if compact_metadata_text is None:
        compact_metadata_text = _render_right_text(metadata_text, console=console, options=line_options, compact=True)
    if cell_len(compact_metadata_text.plain) <= max_width:
        return compact_metadata_text
    return truncate_left(compact_metadata_text, max(1, max_width), console=console)


class _StatusShimmerLine:
    def __init__(self, *, main: Text) -> None:
        self._main = main

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        max_width = getattr(options, "max_width", options.size.width)

        main_text = Text()
        for index, (ch, intensity) in enumerate(_shimmer_profile(self._main.plain)):
            base_style = self._main.get_style_at_offset(console, index)
            style = _shimmer_style(console, base_style, intensity)
            main_text.append(ch, style=style)

        yield truncate_status(main_text, max(1, max_width), console=console)


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
        if not self.text:
            return Text()
        if isinstance(self.text, (str, Text)):
            return self.text if isinstance(self.text, Text) else Text(self.text)
        return self.text


# Monkey-patch Rich's Status module to use the breathing spinner implementation
# for the configured spinner name, while preserving default behavior elsewhere.
# Best-effort patch; if it fails we silently fall back to default spinner.
with contextlib.suppress(Exception):
    rich_status.Spinner = BreathingSpinner  # type: ignore[assignment]
