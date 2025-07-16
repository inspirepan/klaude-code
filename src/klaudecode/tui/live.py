"""
Custom LiveRender and Live classes with crop_above functionality
"""

from rich._loop import loop_last
from rich.console import Console, ConsoleOptions, RenderResult
from rich.live import Live
from rich.live_render import LiveRender
from rich.segment import Segment


class CropAboveLiveRender(LiveRender):
    """Extended LiveRender with crop_above mode support"""

    def __init__(
        self,
        renderable,
        style='',
    ) -> None:
        # Call parent initialization with supported value first
        super().__init__(renderable, style, 'ellipsis')

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        """Override rendering method to support crop_above"""
        renderable = self.renderable
        style = console.get_style(self.style)
        lines = console.render_lines(renderable, options, style=style, pad=False)
        shape = Segment.get_shape(lines)

        _, height = shape
        if height > options.size.height:
            # crop above
            lines = lines[-(options.size.height) :]
            shape = Segment.get_shape(lines)

        self._shape = shape

        new_line = Segment.line()
        for last, line in loop_last(lines):
            yield from line
            if not last:
                yield new_line


class CropAboveLive(Live):
    """Live with vertical overflow crop above"""

    def __init__(
        self,
        renderable=None,
        *,
        console=None,
        screen=False,
        auto_refresh=True,
        refresh_per_second=4,
        transient=False,
        redirect_stdout=True,
        redirect_stderr=True,
        get_renderable=None,
    ) -> None:
        super().__init__(
            renderable,
            console=console,
            screen=screen,
            auto_refresh=auto_refresh,
            refresh_per_second=refresh_per_second,
            transient=transient,
            redirect_stdout=redirect_stdout,
            redirect_stderr=redirect_stderr,
            vertical_overflow='ellipsis',  # Parent class only accepts original values
            get_renderable=get_renderable,
        )
        # Replace with our CropAboveLiveRender
        self._live_render = CropAboveLiveRender(self.get_renderable())
