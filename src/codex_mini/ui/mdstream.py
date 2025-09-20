# copy from https://github.com/Aider-AI/aider/blob/main/aider/mdstream.py
import io
import time
from typing import Any, ClassVar

from rich.console import Console, ConsoleOptions, Group, RenderResult
from rich.live import Live
from rich.markdown import CodeBlock, Heading, Markdown
from rich.rule import Rule
from rich.style import Style
from rich.syntax import Syntax
from rich.text import Text
from rich.theme import Theme
from rich.spinner import Spinner


class NoInsetCodeBlock(CodeBlock):
    """A code block with syntax highlighting and no padding."""

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        code = str(self.text).rstrip()
        syntax = Syntax(
            code,
            self.lexer_name,
            theme=self.theme,
            word_wrap=True,
            padding=(1, 0),
        )
        yield syntax


class LeftHeading(Heading):
    """A heading class that renders left-justified."""

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        text = self.text
        text.justify = "left"  # Override justification
        if self.tag == "h2":
            text.stylize(Style(bold=True, underline=False))
            yield Rule(title=text, characters="-", style="markdown.h2.border", align="left")
        else:
            yield text


class NoInsetMarkdown(Markdown):
    """Markdown with code blocks that have no padding and left-justified headings."""

    elements: ClassVar[dict[str, type[Any]]] = {
        **Markdown.elements,
        "fence": NoInsetCodeBlock,
        "code_block": NoInsetCodeBlock,
        "heading_open": LeftHeading,
    }


class MarkdownStream:
    """Streaming markdown renderer that progressively displays content with a live updating window.

    Uses rich.console and rich.live to render markdown content with smooth scrolling
    and partial updates. Maintains a sliding window of visible content while streaming
    in new markdown text.
    """

    def __init__(
        self,
        mdargs: dict[str, Any] | None = None,
        theme: Theme | None = None,
        console: Console | None = None,
        spinner: Spinner | None = None,
    ):
        """Initialize the markdown stream.

        Args:
            mdargs (dict, optional): Additional arguments to pass to rich Markdown renderer
            theme (Theme, optional): Theme for rendering markdown
            console (Console, optional): External console to use for rendering
        """
        self.printed: list[str] = []  # Stores lines that have already been printed

        if mdargs:
            self.mdargs: dict[str, Any] = mdargs
        else:
            self.mdargs = {}

        # Defer Live creation until the first update.
        self.live: Live | None = None
        self._live_started: bool = False

        # Streaming control
        self.when: float = 0.0  # Timestamp of last update
        self.min_delay: float = 1.0 / 20  # Minimum time between updates (20fps)
        self.live_window: int = 20  # Number of lines to keep visible at bottom

        self.theme = theme
        self.console = console or Console()

        self.spinner = spinner

    def _render_markdown_to_lines(self, text: str) -> list[str]:
        """Render markdown text to a list of lines.

        Args:
            text (str): Markdown text to render

        Returns:
            list: List of rendered lines with line endings preserved
        """
        # Render the markdown to a string buffer
        string_io = io.StringIO()
        # Use external console for consistent theming, or create temporary one
        # Use external console settings but render to string_io
        # Use the console's actual width to avoid reflow glitches.
        temp_console = Console(
            file=string_io,
            force_terminal=True,
            theme=self.theme,
            width=self.console.width,
        )

        markdown = NoInsetMarkdown(text, **self.mdargs)
        temp_console.print(markdown)
        output = string_io.getvalue()

        # Split rendered output into lines
        return output.splitlines(keepends=True)

    def __del__(self) -> None:
        """Destructor to ensure Live display is properly cleaned up."""
        if self.live:
            try:
                self.live.stop()
            except Exception:
                pass  # Ignore any errors during cleanup

    def update(self, text: str, final: bool = False) -> None:
        """Update the displayed markdown content.

        Args:
            text (str): The markdown text received so far
            final (bool): If True, this is the final update and we should clean up

        Splits the output into "stable" older lines and the "last few" lines
        which aren't considered stable. They may shift around as new chunks
        are appended to the markdown text.

        The stable lines emit to the console above the Live window.
        The unstable lines emit into the Live window so they can be repainted.

        Markdown going to the console works better in terminal scrollback buffers.
        The live window doesn't play nice with terminal scrollback.
        """
        # On the first call, stop the spinner and start the Live renderer
        if not getattr(self, "_live_started", False):
            self.live = Live(
                Text(""),
                refresh_per_second=1.0 / self.min_delay,
                console=self.console,  # Use external console if provided
            )
            self.live.start()
            self._live_started = True

        # If live rendering isn't available (e.g., after a final update), stop.
        if self.live is None:
            return

        now = time.time()
        # Throttle updates to maintain smooth rendering
        if not final and now - self.when < self.min_delay:
            return
        self.when = now

        # Measure render time and adjust min_delay to maintain smooth rendering
        start = time.time()
        lines = self._render_markdown_to_lines(text)
        render_time = time.time() - start

        # Set min_delay to render time plus a small buffer
        self.min_delay = min(max(render_time * 10, 1.0 / 20), 2)

        # Determine the number of stable lines (clamped to non-negative)
        total = len(lines)
        stable_count = total if final else max(0, total - self.live_window)

        current_width = self.console.width
        # Store last width on the instance; default to None
        if not hasattr(self, "_last_width"):
            self._last_width = current_width
        elif self._last_width != current_width:
            self.printed = []
            self._last_width = current_width

        # Print any new stable lines above the live window
        num_printed = len(self.printed)
        to_show = stable_count - num_printed
        if to_show > 0:
            chunk = "".join(lines[num_printed:stable_count])
            renderable = Text.from_ansi(chunk)
            self.console.print(renderable)
            self.printed = lines[:stable_count]

        # Always refresh the live window with the latest unstable tail
        window_lines = lines[stable_count:]
        window_text = Text.from_ansi("".join(window_lines)) if window_lines else Text("")
        self.live.update(Group(window_text, self.spinner) if self.spinner else window_text)

        # Handle final update cleanup
        if final:
            live = self.live
            assert live is not None
            live.update(Text(""))
            live.stop()
            self.live = None
            return

    def find_minimal_suffix(self, text: str, match_lines: int = 50) -> None:
        """
        Splits text into chunks on blank lines "\n\n".
        """
        return None
