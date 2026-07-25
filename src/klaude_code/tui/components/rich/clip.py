from typing import TYPE_CHECKING

from rich.console import Console, ConsoleOptions, RenderResult
from rich.measure import Measurement
from rich.segment import Segment
from rich.style import Style

if TYPE_CHECKING:
    from rich.console import RenderableType


class MaxLines:
    """Clip a renderable to at most `max_lines`, marking the cut with an ellipsis.

    Lets content wrap naturally first, so a long value spreads over a few lines
    instead of being flattened into one ellipsised row.
    """

    def __init__(
        self,
        renderable: "RenderableType",
        max_lines: int,
        *,
        ellipsis_style: str | Style | None = None,
        wrap: bool = False,
    ) -> None:
        self.renderable = renderable
        self.max_lines = max(1, max_lines)
        self.ellipsis_style = ellipsis_style
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
                console.get_style(self.ellipsis_style)
                if isinstance(self.ellipsis_style, str)
                else self.ellipsis_style
            )
        for index, line in enumerate(visible):
            if clipped and index == len(visible) - 1:
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

    def __rich_measure__(self, console: Console, options: ConsoleOptions) -> Measurement:
        return Measurement.get(console, self._content_options(options), self.renderable)
