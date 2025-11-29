from typing import Any

from rich.console import Console, ConsoleOptions, RenderResult
from rich.segment import Segment
from rich.style import Style


class Quote:
    """Wrapper to add quote prefix to any content"""

    def __init__(self, content: Any, prefix: str = "▌ ", style: str | Style = "magenta"):
        self.content = content
        self.prefix = prefix
        self.style = style

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        # Reduce width to leave space for prefix
        prefix_width = len(self.prefix)
        render_options = options.update(width=options.max_width - prefix_width)

        # Get style
        quote_style = console.get_style(self.style) if isinstance(self.style, str) else self.style

        # Add prefix to each line
        prefix_segment = Segment(self.prefix, quote_style)
        new_line = Segment("\n")

        # Render content as lines
        lines = console.render_lines(self.content, render_options)

        for line in lines:
            yield prefix_segment
            yield from line
            yield new_line
