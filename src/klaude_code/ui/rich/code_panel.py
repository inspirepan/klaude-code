"""A panel that only has top and bottom borders, no left/right borders or padding."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.cells import cell_len
from rich.console import ConsoleRenderable, RichCast
from rich.jupyter import JupyterMixin
from rich.measure import Measurement
from rich.segment import Segment
from rich.style import StyleType

if TYPE_CHECKING:
    from rich.console import Console, ConsoleOptions, RenderResult

# Box drawing characters
TOP_LEFT = "┌"  # ┌
TOP_RIGHT = "┐"  # ┐
BOTTOM_LEFT = "└"  # └
BOTTOM_RIGHT = "┘"  # ┘
HORIZONTAL = "─"  # ─


class CodePanel(JupyterMixin):
    """A panel with only top and bottom borders, no left/right borders.

    This is designed for code blocks where you want easy copy-paste without
    picking up border characters on the sides.

    Example:
        >>> console.print(CodePanel(Syntax(code, "python")))

    Renders as:
        ┌──────────────────────────┐
        code line 1
        code line 2
        └──────────────────────────┘
    """

    def __init__(
        self,
        renderable: ConsoleRenderable | RichCast | str,
        *,
        border_style: StyleType = "none",
        expand: bool = False,
        padding: int = 1,
    ) -> None:
        """Initialize the CodePanel.

        Args:
            renderable: A console renderable object.
            border_style: The style of the border. Defaults to "none".
            expand: If True, expand to fill available width. Defaults to False.
            padding: Left/right padding for content. Defaults to 1.
        """
        self.renderable = renderable
        self.border_style = border_style
        self.expand = expand
        self.padding = padding

    @staticmethod
    def _measure_max_line_cells(lines: list[list[Segment]]) -> int:
        max_cells = 0
        for line in lines:
            plain = "".join(segment.text for segment in line).rstrip()
            max_cells = max(max_cells, cell_len(plain))
        return max_cells

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        border_style = console.get_style(self.border_style)
        max_width = options.max_width
        pad = self.padding

        max_content_width = max(max_width - pad * 2, 1)

        # Measure the content width (account for padding)
        if self.expand:
            content_width = max_content_width
        else:
            probe_options = options.update(width=max_content_width)
            probe_lines = console.render_lines(self.renderable, probe_options, pad=False)
            content_width = self._measure_max_line_cells(probe_lines)
            content_width = max(1, min(content_width, max_content_width))

        # Render content lines
        child_options = options.update(width=content_width)
        lines = console.render_lines(self.renderable, child_options)

        # Calculate border width based on content width + padding
        border_width = content_width + pad * 2

        new_line = Segment.line()
        pad_segment = Segment(" " * pad) if pad > 0 else None

        # Top border: ┌───...───┐
        top_border = (
            TOP_LEFT + (HORIZONTAL * (border_width - 2)) + TOP_RIGHT if border_width >= 2 else HORIZONTAL * border_width
        )
        yield Segment(top_border, border_style)
        yield new_line

        # Content lines with padding
        for line in lines:
            if pad_segment:
                yield pad_segment
            yield from line
            if pad_segment:
                yield pad_segment
            yield new_line

        # Bottom border: └───...───┘
        bottom_border = (
            BOTTOM_LEFT + (HORIZONTAL * (border_width - 2)) + BOTTOM_RIGHT
            if border_width >= 2
            else HORIZONTAL * border_width
        )
        yield Segment(bottom_border, border_style)
        yield new_line

    def __rich_measure__(self, console: Console, options: ConsoleOptions) -> Measurement:
        if self.expand:
            return Measurement(options.max_width, options.max_width)
        max_width = options.max_width
        max_content_width = max(max_width - self.padding * 2, 1)
        probe_options = options.update(width=max_content_width)
        probe_lines = console.render_lines(self.renderable, probe_options, pad=False)
        content_width = self._measure_max_line_cells(probe_lines)
        content_width = max(1, min(content_width, max_content_width))
        width = content_width + self.padding * 2
        return Measurement(width, width)
