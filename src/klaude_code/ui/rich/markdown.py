# copy from https://github.com/Aider-AI/aider/blob/main/aider/mdstream.py
from __future__ import annotations

import contextlib
import io
import time
from collections.abc import Callable
from typing import Any, ClassVar

from rich.console import Console, ConsoleOptions, Group, RenderableType, RenderResult
from rich.live import Live
from rich.markdown import CodeBlock, Heading, Markdown
from rich.rule import Rule
from rich.spinner import Spinner
from rich.style import Style
from rich.syntax import Syntax
from rich.text import Text
from rich.theme import Theme

from klaude_code import const
from klaude_code.ui.rich.code_panel import CodePanel


class NoInsetCodeBlock(CodeBlock):
    """A code block with syntax highlighting and no padding."""

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        code = str(self.text).rstrip()
        syntax = Syntax(
            code,
            self.lexer_name,
            theme=self.theme,
            word_wrap=True,
            padding=(0, 0),
        )
        yield CodePanel(syntax, border_style="markdown.code.border")


class ThinkingCodeBlock(CodeBlock):
    """A code block for thinking content that uses grey styling instead of syntax highlighting."""

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        code = str(self.text).rstrip()
        text = Text(code, "markdown.code.block")
        yield CodePanel(text, border_style="markdown.code.border")


class LeftHeading(Heading):
    """A heading class that renders left-justified."""

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        text = self.text
        text.justify = "left"  # Override justification
        if self.tag == "h1":
            h1_text = text.assemble((" ", "markdown.h1"), text, (" ", "markdown.h1"))
            yield h1_text
        elif self.tag == "h2":
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


class ThinkingMarkdown(Markdown):
    """Markdown for thinking content with grey-styled code blocks and left-justified headings."""

    elements: ClassVar[dict[str, type[Any]]] = {
        **Markdown.elements,
        "fence": ThinkingCodeBlock,
        "code_block": ThinkingCodeBlock,
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
        mark: str | None = None,
        indent: int = 0,
        markdown_class: Callable[..., Markdown] | None = None,
    ) -> None:
        """Initialize the markdown stream.

        Args:
            mdargs (dict, optional): Additional arguments to pass to rich Markdown renderer
            theme (Theme, optional): Theme for rendering markdown
            console (Console, optional): External console to use for rendering
            mark (str | None, optional): Marker shown before the first non-empty line when indent >= 2
            indent (int, optional): Number of spaces to indent all rendered lines on the left
            markdown_class: Markdown class to use for rendering (defaults to NoInsetMarkdown)
        """
        self.printed: list[str] = []  # Stores lines that have already been printed

        if mdargs:
            self.mdargs: dict[str, Any] = mdargs
        else:
            self.mdargs = {}

        # Defer Live creation until the first update.
        self.live: Live | None = None

        # Streaming control
        self.when: float = 0.0  # Timestamp of last update
        self.min_delay: float = 1.0 / 20  # Minimum time between updates (20fps)
        self.live_window: int = const.MARKDOWN_STREAM_LIVE_WINDOW

        self.theme = theme
        self.console = console
        self.spinner: Spinner | None = spinner
        self.mark: str | None = mark
        self.indent: int = max(indent, 0)
        self.markdown_class: Callable[..., Markdown] = markdown_class or NoInsetMarkdown

    @property
    def _live_started(self) -> bool:
        """Check if Live display has been started (derived from self.live)."""
        return self.live is not None

    def _render_markdown_to_lines(self, text: str) -> list[str]:
        """Render markdown text to a list of lines.

        Args:
            text (str): Markdown text to render

        Returns:
            list: List of rendered lines with line endings preserved
        """
        # Render the markdown to a string buffer
        string_io = io.StringIO()

        # Determine console width and adjust for left indent so that
        # the rendered content plus indent does not exceed the available width.
        if self.console is not None:
            base_width = self.console.options.max_width
        else:
            probe_console = Console(theme=self.theme)
            base_width = probe_console.options.max_width

        effective_width = max(base_width - self.indent, 1)

        # Use external console for consistent theming, or create temporary one
        temp_console = Console(
            file=string_io,
            force_terminal=True,
            theme=self.theme,
            width=effective_width,
        )

        markdown = self.markdown_class(text, **self.mdargs)
        temp_console.print(markdown)
        output = string_io.getvalue()

        # Split rendered output into lines, strip trailing spaces, and apply left indent.
        lines = output.splitlines(keepends=True)
        indent_prefix = " " * self.indent if self.indent > 0 else ""
        processed_lines: list[str] = []
        mark_applied = False
        use_mark = bool(self.mark) and self.indent >= 2

        for line in lines:
            stripped = line.rstrip()

            # Apply mark to the first non-empty line only when indent is at least 2.
            if use_mark and not mark_applied and stripped:
                stripped = f"{self.mark} {stripped}"
                mark_applied = True
            elif indent_prefix:
                stripped = indent_prefix + stripped

            if line.endswith("\n"):
                stripped += "\n"
            processed_lines.append(stripped)

        return processed_lines

    def __del__(self) -> None:
        """Destructor to ensure Live display is properly cleaned up."""
        if self.live:
            # Ignore any errors during cleanup
            with contextlib.suppress(Exception):
                self.live.stop()

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
        if not self._live_started:
            initial_content = self._live_renderable(Text(""), final=False)
            # transient=False keeps final frame on screen after stop()
            self.live = Live(
                initial_content,
                refresh_per_second=1.0 / self.min_delay,
                console=self.console,
            )
            self.live.start()

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

        num_lines = len(lines)

        # Reserve last live_window lines for Live area to keep height stable
        num_lines = max(num_lines - self.live_window, 0)

        # Print new stable lines above Live window
        if num_lines > 0:
            num_printed = len(self.printed)
            to_append_count = num_lines - num_printed

            if to_append_count > 0:
                append_chunk = lines[num_printed:num_lines]
                append_chunk_text = Text.from_ansi("".join(append_chunk))
                live = self.live
                assert live is not None
                live.console.print(append_chunk_text)
                self.printed = lines[:num_lines]

        rest_lines = lines[num_lines:]

        # Final: render remaining lines without spinner, then stop Live
        if final:
            live = self.live
            assert live is not None
            rest = "".join(rest_lines)
            rest_text = Text.from_ansi(rest)
            final_renderable = self._live_renderable(rest_text, final=True)
            live.update(final_renderable)
            live.stop()
            self.live = None
            return

        rest = "".join(rest_lines)
        rest = Text.from_ansi(rest)
        live = self.live
        assert live is not None
        live_renderable = self._live_renderable(rest, final)
        live.update(live_renderable)

    def _live_renderable(self, rest: Text, final: bool) -> RenderableType:
        if final or not self.spinner:
            return rest
        else:
            return Group(rest, Text(), self.spinner)

    def find_minimal_suffix(self, text: str, match_lines: int = 50) -> None:
        """
        Splits text into chunks on blank lines "\n\n".
        """
        return None
