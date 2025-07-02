from types import TracebackType
from typing import Optional, Type

from rich.columns import Columns
from rich.console import Console, Group, RenderableType, StyleType
from rich.live import Live
from rich.spinner import Spinner
from rich.text import Text

from .colors import ColorStyle
from .console import console

INTERRUPT_TIP = '  press ctrl+c to interrupt  '


class DotsStatus:
    def __init__(
        self,
        status: RenderableType,
        description: Optional[RenderableType] = None,
        *,
        console: Console = Console(),
        spinner: str = 'dots',
        spinner_style: StyleType = None,
        dots_style: StyleType = None,
        refresh_per_second: int = 10,
        width: int = 10,
    ):
        self.status = status
        self.description = description
        self.spinner = spinner
        self.spinner_style = spinner_style
        self.dots_style = dots_style
        self.refresh_per_second = refresh_per_second
        self.width = width
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
        spinner: Optional[str] = None,
        spinner_style: Optional[StyleType] = None,
        dots_style: Optional[StyleType] = None,
    ):
        if status:
            self.status = status
        if description:
            self.description = description
        if spinner:
            self.spinner = spinner
        if spinner_style:
            self.spinner_style = spinner_style
        if dots_style:
            self.dots_style = dots_style
        self._live.update(self.renderable, refresh=True)

    @property
    def renderable(self) -> Columns:
        spacing = max(self.width - len(self.status) + 1, 1)
        return Group(
            '',
            Columns(
                [
                    Spinner(name=self.spinner, style=self.spinner_style),
                    ' ',
                    self.status,
                    Spinner(name='simpleDots', style=self.dots_style, speed=1),
                    ' ' * spacing,
                    self.description,
                ],
                padding=(0, 0),
            ),
        )

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
    spinner: str = 'dots',
    spinner_style: StyleType = None,
    dots_style: StyleType = None,
    width: int = 10,
):
    if description:
        desc_text = Text.assemble(description, (INTERRUPT_TIP, ColorStyle.MUTED))
    else:
        desc_text = Text(INTERRUPT_TIP, style=ColorStyle.MUTED)
    return DotsStatus(
        status=status,
        description=desc_text,
        console=console.console,
        spinner=spinner,
        spinner_style=spinner_style,
        dots_style=dots_style,
        width=width,
    )
