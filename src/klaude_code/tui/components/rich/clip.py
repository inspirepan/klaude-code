from typing import TYPE_CHECKING

from rich.console import Console, ConsoleOptions, RenderResult
from rich.measure import Measurement
from rich.segment import Segment
from rich.style import Style
from rich.text import Text

if TYPE_CHECKING:
    from rich.console import RenderableType


class MaxLines:
    """Clip a renderable to `max_lines`, marking the cut with an ellipsis or hint.

    Lets content wrap naturally first, so a long value spreads over a few lines
    instead of being flattened into one ellipsised row. An expand hint adds a
    separate omission-count row after the preview.
    """

    def __init__(
        self,
        renderable: "RenderableType",
        max_lines: int,
        *,
        ellipsis_style: str | Style | None = None,
        wrap: bool = False,
        expand_hint: str | None = None,
    ) -> None:
        self.renderable = renderable
        self.max_lines = max(1, max_lines)
        self.ellipsis_style = ellipsis_style
        self.expand_hint = expand_hint
        # Callers that want several lines out of a single-line context (the
        # status bar forces no_wrap/height=1) opt in here.
        self.wrap = wrap

    def _content_options(self, options: ConsoleOptions) -> ConsoleOptions:
        if not self.wrap:
            return options
        return options.update(no_wrap=False, overflow="fold", height=None)

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        lines = console.render_lines(self.renderable, self._content_options(options), pad=False)
        clipped = len(lines) > self.max_lines
        visible = lines[: self.max_lines]
        style = None
        if clipped and self.ellipsis_style is not None:
            style = (
                console.get_style(self.ellipsis_style) if isinstance(self.ellipsis_style, str) else self.ellipsis_style
            )
        for index, line in enumerate(visible):
            if clipped and self.expand_hint is None and index == len(visible) - 1:
                # Only shorten a line that actually fills the width; otherwise the
                # ellipsis should sit right after the text, not at the far margin.
                if Segment.get_line_length(line) >= options.max_width:
                    yield from Segment.adjust_line_length(line, max(0, options.max_width - 1))
                else:
                    yield from line
                yield Segment("…", style)
            else:
                yield from line
            yield Segment("\n")
        if clipped and self.expand_hint is not None:
            yield from console.render(
                Text(f"… {len(lines) - self.max_lines} more lines · {self.expand_hint}", style=style or ""),
                options,
            )

    def __rich_measure__(self, console: Console, options: ConsoleOptions) -> Measurement:
        return Measurement.get(console, self._content_options(options), self.renderable)
