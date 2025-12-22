from __future__ import annotations

from typing import Any

from rich._loop import loop_last
from rich.console import Console, ConsoleOptions, RenderableType, RenderResult
from rich.live import Live
from rich.segment import Segment


class CropAbove:
    def __init__(self, renderable: RenderableType, style: str = "") -> None:
        self.renderable = renderable
        self.style = style

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        style = console.get_style(self.style) if self.style else None
        lines = console.render_lines(self.renderable, options, style=style, pad=False)
        max_height = options.size.height
        if len(lines) > max_height:
            lines = lines[-max_height:]

        new_line = Segment.line()
        for last, line in loop_last(lines):
            yield from line
            if not last:
                yield new_line


class CropAboveLive(Live):
    def __init__(
        self,
        renderable: RenderableType | None = None,
        *,
        console: Console | None = None,
        refresh_per_second: float = 4,
        transient: bool = False,
        get_renderable: Any | None = None,
        style: str = "",
        **kwargs: Any,
    ) -> None:
        self._crop_style: str = style

        if get_renderable is not None:

            def _wrapped_get() -> RenderableType:
                assert get_renderable is not None
                return CropAbove(get_renderable(), style=self._crop_style)

            get_renderable = _wrapped_get

        if renderable is not None:
            renderable = CropAbove(renderable, style=self._crop_style)

        super().__init__(
            renderable,
            console=console,
            refresh_per_second=refresh_per_second,
            transient=transient,
            get_renderable=get_renderable,
            **kwargs,
        )

    def update(self, renderable: RenderableType, refresh: bool = True) -> None:  # type: ignore[override]
        super().update(CropAbove(renderable, style=self._crop_style), refresh=refresh)


class SingleLine:
    """Render only the first line of a renderable.

    This is used to ensure dynamic UI elements (spinners / status) never wrap
    to multiple lines, which would appear as a vertical "jump".
    """

    def __init__(self, renderable: RenderableType) -> None:
        self.renderable = renderable

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        line_options = options.update(no_wrap=True, overflow="ellipsis", height=1)
        lines = console.render_lines(self.renderable, line_options, pad=False)
        if lines:
            yield from lines[0]
