import os
from types import TracebackType
from typing import Optional, Type

from rich.columns import Columns
from rich.console import Console, ConsoleOptions, Group, RenderableType, StyleType
from rich.live import Live
from rich.measure import Measurement
from rich.spinner import Spinner
from rich.text import Text

from .colors import ColorStyle
from .console import console

INTERRUPT_TIP = ' (ctrl+c to interrupt)'


class CustomSpinner:
    def __init__(self, frames, interval_ms=100, style: StyleType = None):
        self.frames = frames
        self.interval = interval_ms / 1000.0
        self.start_time = None
        self.style = style

    def __rich_console__(self, console, options):
        yield self.render(console.get_time())

    def render(self, time_now):
        if self.start_time is None:
            self.start_time = time_now

        elapsed = time_now - self.start_time
        frame_index = int(elapsed / self.interval) % len(self.frames)
        frame_text = self.frames[frame_index]
        return Text(frame_text, style=self.style)

    def __rich_measure__(self, console: 'Console', options: 'ConsoleOptions') -> Measurement:
        return Measurement.get(console, options, self.frames[0])


claude_frames = [
    '✶',
    '✻',
    '✽',
    '✻',
    '✶',
    '✳',
    '✢',
    '·',
    '✢',
    '✳',
]

weather_frames = [
    '☀️ ',
    '☀️ ',
    '☀️ ',
    '🌤 ',
    '⛅️ ',
    '🌥 ',
    '☁️ ',
    '🌧 ',
    '🌨 ',
    '🌧 ',
    '🌨 ',
    '🌧 ',
    '🌨 ',
    '🌨 ',
    '🌧 ',
    '🌨 ',
    '☁️ ',
    '🌥 ',
    '⛅️ ',
    '🌤 ',
    '☀️ ',
    '☀️ ',
]

_USE_BONUS_SPINNER = os.environ.get('TRANSIENCE') == '1'


def get_spinner(style: StyleType = None):
    if _USE_BONUS_SPINNER:
        return CustomSpinner(weather_frames, interval_ms=100, style=style)
    return CustomSpinner(claude_frames, interval_ms=100, style=style)


class DotsStatus:
    def __init__(
        self,
        status: RenderableType,
        description: Optional[RenderableType] = None,
        *,
        console: Console = Console(),
        spinner_style: StyleType = ColorStyle.STATUS,
        dots_style: StyleType = ColorStyle.STATUS,
        refresh_per_second: int = 10,
        padding_line: bool = True,
    ):
        self.status = status
        self.description = description
        self.spinner = get_spinner(style=spinner_style)
        self.dots = Spinner(name='simpleDots', style=dots_style, speed=1)
        self.refresh_per_second = refresh_per_second
        self.padding_line = padding_line
        self._live = Live(
            self.renderable,
            console=console,
            refresh_per_second=self.refresh_per_second,
            transient=True,
        )

    def update(
        self,
        *,
        status: Optional[RenderableType] = None,
        description: Optional[RenderableType] = None,
        spinner_style: Optional[StyleType] = None,
        dots_style: Optional[StyleType] = None,
    ):
        if status:
            self.status = status
        if description:
            self.description = description
        if spinner_style:
            self.spinner = get_spinner(style=spinner_style)
        if dots_style:
            self.dots = Spinner(name='simpleDots', style=dots_style, speed=1)
        self._live.update(self.renderable, refresh=True)

    @property
    def renderable(self) -> Columns:
        columns = Columns(
            [
                self.spinner,
                '  ',
                self.status,
                self.dots,
                ' ',
                self.description,
            ],
            padding=(0, 0),
        )
        if self.padding_line:
            return Group(
                '',
                columns,
            )
        return columns

    def start(self) -> None:
        """Start the status animation."""
        self._live.start()

    def stop(self) -> None:
        """Stop the spinner animation."""
        self._live.stop()

    def __rich__(self) -> RenderableType:
        return self.renderable

    def __enter__(self) -> 'DotsStatus':
        self.start()
        return self

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> None:
        self.stop()


def render_dot_status(
    status: str,
    description: Optional[str] = None,
    spinner_style: StyleType = ColorStyle.STATUS,
    dots_style: StyleType = ColorStyle.STATUS,
    padding_line: bool = True,
):
    if description:
        desc_text = Text.assemble(description, (INTERRUPT_TIP, ColorStyle.HINT))
    else:
        desc_text = Text(INTERRUPT_TIP, style=ColorStyle.HINT)
    return DotsStatus(
        status=status,
        description=desc_text,
        console=console.console,
        spinner_style=spinner_style,
        dots_style=dots_style,
        padding_line=padding_line,
    )
