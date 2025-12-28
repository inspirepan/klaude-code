from __future__ import annotations

import contextlib
import io
import time
from collections.abc import Callable
from typing import Any, ClassVar

from markdown_it import MarkdownIt
from markdown_it.token import Token
from rich import box
from rich.console import Console, ConsoleOptions, RenderableType, RenderResult
from rich.markdown import CodeBlock, Heading, Markdown, MarkdownElement, TableElement
from rich.rule import Rule
from rich.style import Style, StyleType
from rich.syntax import Syntax
from rich.table import Table
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


class Divider(MarkdownElement):
    """A horizontal rule with an extra blank line below."""

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        style = console.get_style("markdown.hr", default="none")
        yield Rule(style=style, characters="-")


class MarkdownTable(TableElement):
    """A table element with MINIMAL_HEAVY_HEAD box style."""

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        table = Table(box=box.MARKDOWN, border_style=console.get_style("markdown.table.border"))

        if self.header is not None and self.header.row is not None:
            for column in self.header.row.cells:
                table.add_column(column.content)

        if self.body is not None:
            for row in self.body.rows:
                row_content = [element.content for element in row.cells]
                table.add_row(*row_content)

        yield table


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
            yield text
        else:
            yield text


class NoInsetMarkdown(Markdown):
    """Markdown with code blocks that have no padding and left-justified headings."""

    elements: ClassVar[dict[str, type[Any]]] = {
        **Markdown.elements,
        "fence": NoInsetCodeBlock,
        "code_block": NoInsetCodeBlock,
        "heading_open": LeftHeading,
        "hr": Divider,
        "table_open": MarkdownTable,
    }


class ThinkingMarkdown(Markdown):
    """Markdown for thinking content with grey-styled code blocks and left-justified headings."""

    elements: ClassVar[dict[str, type[Any]]] = {
        **Markdown.elements,
        "fence": ThinkingCodeBlock,
        "code_block": ThinkingCodeBlock,
        "heading_open": LeftHeading,
        "hr": Divider,
        "table_open": MarkdownTable,
    }


class MarkdownStream:
    """Block-based streaming Markdown renderer.

    This renderer is optimized for terminal UX:

    - Stable area: only prints *completed* Markdown blocks to scrollback (append-only).
    - Live area: continuously repaints only the final *possibly incomplete* block.

    Block boundaries are computed with `MarkdownIt("commonmark")` (token maps / top-level tokens).
    Rendering is done with Rich Markdown (customizable via `markdown_class`).
    """

    def __init__(
        self,
        console: Console,
        mdargs: dict[str, Any] | None = None,
        theme: Theme | None = None,
        live_sink: Callable[[RenderableType | None], None] | None = None,
        mark: str | None = None,
        mark_style: StyleType | None = None,
        left_margin: int = 0,
        right_margin: int = const.MARKDOWN_RIGHT_MARGIN,
        markdown_class: Callable[..., Markdown] | None = None,
    ) -> None:
        """Initialize the markdown stream.

        Args:
            mdargs (dict, optional): Additional arguments to pass to rich Markdown renderer
            theme (Theme, optional): Theme for rendering markdown
            console (Console, optional): External console to use for rendering
            mark (str | None, optional): Marker shown before the first non-empty line when left_margin >= 2
            mark_style (StyleType | None, optional): Style to apply to the mark
            left_margin (int, optional): Number of columns to reserve on the left side
            right_margin (int, optional): Number of columns to reserve on the right side
            markdown_class: Markdown class to use for rendering (defaults to NoInsetMarkdown)
        """
        self._stable_rendered_lines: list[str] = []
        self._stable_source_line_count: int = 0

        if mdargs:
            self.mdargs: dict[str, Any] = mdargs
        else:
            self.mdargs = {}

        self._live_sink = live_sink

        # Streaming control
        self.when: float = 0.0  # Timestamp of last update
        self.min_delay: float = 1.0 / 20  # Minimum time between updates (20fps)
        self._parser: MarkdownIt = MarkdownIt("commonmark")

        self.theme = theme
        self.console = console
        self.mark: str | None = mark
        self.mark_style: StyleType | None = mark_style

        self.left_margin: int = max(left_margin, 0)

        self.right_margin: int = max(right_margin, 0)
        self.markdown_class: Callable[..., Markdown] = markdown_class or NoInsetMarkdown

    @property
    def _live_started(self) -> bool:
        """Check if Live display has been started (derived from self.live)."""
        return self._live_sink is not None

    def _get_base_width(self) -> int:
        return self.console.options.max_width

    def compute_candidate_stable_line(self, text: str) -> int:
        """Return the start line of the last top-level block, or 0.

        This value is not monotonic; callers should clamp it (e.g. with the
        previous stable line) before using it to advance state.
        """

        try:
            tokens = self._parser.parse(text)
        except Exception:  # markdown-it-py may raise various internal errors during parsing
            return 0

        top_level: list[Token] = [token for token in tokens if token.level == 0 and token.map is not None]
        if len(top_level) < 2:
            return 0

        last = top_level[-1]
        assert last.map is not None
        start_line = last.map[0]
        return max(start_line, 0)

    def split_blocks(self, text: str, *, min_stable_line: int = 0, final: bool = False) -> tuple[str, str, int]:
        """Split full markdown into stable and live sources.

        Returns:
            stable_source: Completed blocks (append-only)
            live_source: Last (possibly incomplete) block
            stable_line: Line index where live starts
        """

        lines = text.splitlines(keepends=True)
        line_count = len(lines)

        stable_line = line_count if final else self.compute_candidate_stable_line(text)

        stable_line = min(stable_line, line_count)
        stable_line = max(stable_line, min_stable_line)

        stable_source = "".join(lines[:stable_line])
        live_source = "".join(lines[stable_line:])
        return stable_source, live_source, stable_line

    def render_ansi(self, text: str, *, apply_mark: bool) -> str:
        """Render markdown source to an ANSI string.

        This is primarily intended for internal debugging and tests.
        """

        return "".join(self._render_markdown_to_lines(text, apply_mark=apply_mark))

    def render_stable_ansi(self, stable_source: str, *, has_live_suffix: bool, final: bool) -> str:
        """Render stable prefix to ANSI, preserving inter-block spacing."""

        if not stable_source:
            return ""

        render_source = stable_source
        if not final and has_live_suffix:
            render_source = self._append_nonfinal_sentinel(stable_source)

        return self.render_ansi(render_source, apply_mark=True)

    @staticmethod
    def normalize_live_ansi_for_boundary(*, stable_ansi: str, live_ansi: str) -> str:
        """Normalize whitespace at the stable/live boundary.

        Some Rich Markdown blocks (e.g. lists) render with a leading blank line.
        If the stable prefix already renders a trailing blank line, rendering the
        live suffix separately may introduce an extra blank line that wouldn't
        appear when rendering the full document.

        This function removes *overlapping* blank lines from the live ANSI when
        the stable ANSI already ends with one or more blank lines.

        Important: don't remove *all* leading blank lines from the live suffix.
        In some incomplete-block cases, the live render may begin with multiple
        blank lines while the full-document render would keep one of them.
        """

        stable_lines = stable_ansi.splitlines(keepends=True)
        if not stable_lines:
            return live_ansi

        stable_trailing_blank = 0
        for line in reversed(stable_lines):
            if line.strip():
                break
            stable_trailing_blank += 1
        if stable_trailing_blank <= 0:
            return live_ansi

        live_lines = live_ansi.splitlines(keepends=True)
        live_leading_blank = 0
        for line in live_lines:
            if line.strip():
                break
            live_leading_blank += 1

        drop = min(stable_trailing_blank, live_leading_blank)
        if drop > 0:
            live_lines = live_lines[drop:]
        return "".join(live_lines)

    def _append_nonfinal_sentinel(self, stable_source: str) -> str:
        """Make Rich render stable content as if it isn't the last block.

        Rich Markdown may omit trailing spacing for the last block in a document.
        When we render only the stable prefix (without the live suffix), we still
        need the *inter-block* spacing to match the full document.

        A harmless HTML comment block causes Rich Markdown to emit the expected
        spacing while rendering no visible content.
        """

        if not stable_source:
            return stable_source

        if stable_source.endswith("\n\n"):
            return stable_source + "<!-- -->"
        if stable_source.endswith("\n"):
            return stable_source + "\n<!-- -->"
        return stable_source + "\n\n<!-- -->"

    def _render_markdown_to_lines(self, text: str, *, apply_mark: bool) -> list[str]:
        """Render markdown text to a list of lines.

        Args:
            text (str): Markdown text to render

        Returns:
            list: List of rendered lines with line endings preserved
        """
        # Render the markdown to a string buffer
        string_io = io.StringIO()

        # Keep width stable across frames to prevent reflow/jitter.
        base_width = self._get_base_width()

        effective_width = max(base_width - self.left_margin - self.right_margin, 1)

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

        # Split rendered output into lines, strip trailing spaces, and apply left margin.
        lines = output.splitlines(keepends=True)
        indent_prefix = " " * self.left_margin if self.left_margin > 0 else ""
        processed_lines: list[str] = []
        mark_applied = False
        use_mark = apply_mark and bool(self.mark) and self.left_margin >= 2

        # Pre-render styled mark if needed
        styled_mark: str | None = None
        if use_mark and self.mark:
            if self.mark_style:
                mark_text = Text(self.mark, style=self.mark_style)
                mark_buffer = io.StringIO()
                mark_console = Console(file=mark_buffer, force_terminal=True, theme=self.theme)
                mark_console.print(mark_text, end="")
                styled_mark = mark_buffer.getvalue()
            else:
                styled_mark = self.mark

        for line in lines:
            stripped = line.rstrip()

            # Apply mark to the first non-empty line only when left_margin is at least 2.
            if use_mark and not mark_applied and stripped:
                stripped = f"{styled_mark} {stripped}"
                mark_applied = True
            elif indent_prefix:
                stripped = indent_prefix + stripped

            if line.endswith("\n"):
                stripped += "\n"
            processed_lines.append(stripped)

        return processed_lines

    def __del__(self) -> None:
        """Destructor to ensure Live display is properly cleaned up."""
        if self._live_sink is None:
            return
        with contextlib.suppress(Exception):
            self._live_sink(None)

    def update(self, text: str, final: bool = False) -> None:
        """Update the display with the latest full markdown buffer."""

        now = time.time()
        if not final and now - self.when < self.min_delay:
            return
        self.when = now

        previous_stable_line = self._stable_source_line_count

        stable_source, live_source, stable_line = self.split_blocks(
            text,
            min_stable_line=previous_stable_line,
            final=final,
        )

        start = time.time()

        stable_changed = final or stable_line > self._stable_source_line_count
        if stable_changed and stable_source:
            stable_ansi = self.render_stable_ansi(stable_source, has_live_suffix=bool(live_source), final=final)
            stable_lines = stable_ansi.splitlines(keepends=True)
            new_lines = stable_lines[len(self._stable_rendered_lines) :]
            if new_lines:
                stable_chunk = "".join(new_lines)
                self.console.print(Text.from_ansi(stable_chunk), end="\n")
            self._stable_rendered_lines = stable_lines
            self._stable_source_line_count = stable_line
        elif final and not stable_source:
            self._stable_rendered_lines = []
            self._stable_source_line_count = stable_line

        if final:
            if self._live_sink is not None:
                self._live_sink(None)
            return

        if const.MARKDOWN_STREAM_LIVE_REPAINT_ENABLED and self._live_sink is not None:
            apply_mark_live = self._stable_source_line_count == 0
            live_lines = self._render_markdown_to_lines(live_source, apply_mark=apply_mark_live)

            if self._stable_rendered_lines:
                stable_trailing_blank = 0
                for line in reversed(self._stable_rendered_lines):
                    if line.strip():
                        break
                    stable_trailing_blank += 1

                if stable_trailing_blank > 0:
                    live_leading_blank = 0
                    for line in live_lines:
                        if line.strip():
                            break
                        live_leading_blank += 1

                    drop = min(stable_trailing_blank, live_leading_blank)
                    if drop > 0:
                        live_lines = live_lines[drop:]

            live_text = Text.from_ansi("".join(live_lines))
            self._live_sink(live_text)

        elapsed = time.time() - start
        self.min_delay = min(max(elapsed * 6, 1.0 / 30), 0.5)
