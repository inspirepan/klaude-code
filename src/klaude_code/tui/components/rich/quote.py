from typing import TYPE_CHECKING, Any, Self

from rich.cells import cell_len
from rich.console import Console, ConsoleOptions, RenderResult
from rich.measure import Measurement
from rich.segment import Segment
from rich.style import Style

if TYPE_CHECKING:
    from rich.console import RenderableType


class Quote:
    """Wrapper to add quote prefix to any content"""

    def __init__(self, content: Any, prefix: str = "▌ ", style: str | Style = "magenta"):
        self.content = content
        self.prefix = prefix
        self.style = style

    def __rich_measure__(self, console: Console, options: ConsoleOptions) -> Measurement:
        prefix_width = cell_len(self.prefix)
        available_width = max(1, options.max_width - prefix_width)
        content_measurement = Measurement.get(console, options.update(width=available_width), self.content)

        minimum = min(options.max_width, content_measurement.minimum + prefix_width)
        maximum = min(options.max_width, content_measurement.maximum + prefix_width)
        return Measurement(minimum, maximum)

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        # Reduce width to leave space for prefix
        prefix_width = cell_len(self.prefix)
        available_width = max(1, options.max_width - prefix_width)
        render_options = options.update(width=available_width)

        # Get style
        quote_style = console.get_style(self.style) if isinstance(self.style, str) else self.style

        # Add prefix to each line
        prefix_segment = Segment(self.prefix, quote_style)
        new_line = Segment("\n")

        # Render content as lines
        # Avoid padding to full width.
        # Trailing spaces can cause terminals to reflow wrapped lines on resize.
        lines = console.render_lines(self.content, render_options, pad=False)

        for line in lines:
            yield prefix_segment
            yield from line
            yield new_line


class TreeQuote:
    """Wrapper to add a tree-style prefix to any content."""

    def __init__(
        self,
        content: Any,
        *,
        prefix_first: str | None = None,
        prefix_middle: str = "│ ",
        prefix_last: str = "└ ",
        style: str | Style = "magenta",
        style_first: str | Style | None = None,
    ):
        self.content = content
        self.prefix_first = prefix_first
        self.prefix_middle = prefix_middle
        self.prefix_last = prefix_last
        self.style = style
        self.style_first = style_first

    def __rich_measure__(self, console: Console, options: ConsoleOptions) -> Measurement:
        prefix_width = max(
            cell_len(self.prefix_middle),
            cell_len(self.prefix_last),
            cell_len(self.prefix_first) if self.prefix_first is not None else 0,
        )
        available_width = max(1, options.max_width - prefix_width)
        content_measurement = Measurement.get(console, options.update(width=available_width), self.content)

        minimum = min(options.max_width, content_measurement.minimum + prefix_width)
        maximum = min(options.max_width, content_measurement.maximum + prefix_width)
        return Measurement(minimum, maximum)

    @classmethod
    def for_tool_call(cls, content: "RenderableType", *, mark: str, style: str, style_first: str) -> Self:
        """Create a tree quote for tool call display.

        The mark appears on the first line, with continuation lines using "│ ".
        """
        return cls(
            content,
            prefix_first=f"{mark} ",
            prefix_middle="│ ",
            prefix_last="│ ",
            style=style,
            style_first=style_first,
        )

    @classmethod
    def for_tool_result(
        cls, content: "RenderableType", *, is_last: bool, style: str = "tool.result.tree_prefix"
    ) -> Self:
        """Create a tree quote for tool result display.

        Uses "└ " for the last result in a turn, "│ " otherwise.
        """
        return cls(content, prefix_last="└ " if is_last else "│ ", style=style)

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        # Reduce width to leave space for prefix
        prefix_width = max(
            cell_len(self.prefix_middle),
            cell_len(self.prefix_last),
            cell_len(self.prefix_first) if self.prefix_first is not None else 0,
        )
        available_width = max(1, options.max_width - prefix_width)
        render_options = options.update(width=available_width)

        quote_style = console.get_style(self.style) if isinstance(self.style, str) else self.style
        first_style = console.get_style(self.style_first) if isinstance(self.style_first, str) else self.style_first

        new_line = Segment("\n")
        lines = console.render_lines(self.content, render_options, pad=False)
        line_count = len(lines)

        for idx, line in enumerate(lines):
            if idx == 0 and self.prefix_first is not None:
                yield Segment(self.prefix_first, first_style or quote_style)
            else:
                is_last = idx == line_count - 1
                prefix = self.prefix_last if is_last else self.prefix_middle
                yield Segment(prefix, quote_style)
            yield from line
            yield new_line
