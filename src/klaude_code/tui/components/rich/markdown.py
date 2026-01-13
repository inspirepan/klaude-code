from __future__ import annotations

import contextlib
import io
import re
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, ClassVar

from markdown_it import MarkdownIt
from markdown_it.token import Token
from rich import box
from rich._loop import loop_first
from rich.console import Console, ConsoleOptions, RenderableType, RenderResult
from rich.markdown import CodeBlock, Heading, ImageItem, ListItem, Markdown, MarkdownElement, TableElement
from rich.segment import Segment
from rich.style import Style, StyleType
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text
from rich.theme import Theme

from klaude_code.const import (
    MARKDOWN_STREAM_LIVE_REPAINT_ENABLED,
    MARKDOWN_STREAM_SYNCHRONIZED_OUTPUT_ENABLED,
    UI_REFRESH_RATE_FPS,
)

_THINKING_HTML_BLOCK_RE = re.compile(
    r"\A\s*<thinking>\s*\n?(?P<body>.*?)(?:\n\s*)?</thinking>\s*\Z",
    flags=re.IGNORECASE | re.DOTALL,
)

_HTML_COMMENT_BLOCK_RE = re.compile(r"\A\s*<!--.*?-->\s*\Z", flags=re.DOTALL)

_CHECKBOX_UNCHECKED_RE = re.compile(r"^\[ \]\s*")
_CHECKBOX_CHECKED_RE = re.compile(r"^\[x\]\s*", re.IGNORECASE)


class ThinkingHTMLBlock(MarkdownElement):
    """Render `<thinking>...</thinking>` HTML blocks as Rich Markdown.

    markdown-it-py treats custom tags like `<thinking>` as HTML blocks, and Rich
    Markdown ignores HTML blocks by default. This element restores visibility by
    re-parsing the inner content as Markdown and applying a dedicated style.

    Non-thinking HTML blocks (including comment sentinels like `<!-- -->`) render
    no visible output, matching Rich's default behavior.
    """

    new_line: ClassVar[bool] = True

    @classmethod
    def create(cls, markdown: Markdown, token: Token) -> ThinkingHTMLBlock:
        return cls(content=token.content or "", code_theme=markdown.code_theme)

    def __init__(self, *, content: str, code_theme: str) -> None:
        self._content = content
        self._code_theme = code_theme

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        stripped = self._content.strip()

        # Keep HTML comments invisible. MarkdownStream relies on a comment sentinel
        # (`<!-- -->`) to preserve inter-block spacing in some streaming frames.
        if _HTML_COMMENT_BLOCK_RE.match(stripped):
            return

        match = _THINKING_HTML_BLOCK_RE.match(stripped)
        if match is None:
            return

        body = match.group("body").strip("\n")
        if not body.strip():
            return

        # Render as a single line to avoid the extra blank lines produced by
        # paragraph/block rendering.
        collapsed = " ".join(body.split())
        if not collapsed:
            return

        text = Text()
        text.append("<thinking>", style="markdown.thinking.tag")
        text.append(collapsed, style="markdown.thinking")
        text.append("</thinking>", style="markdown.thinking.tag")
        yield text


class NoInsetCodeBlock(CodeBlock):
    """A code block with syntax highlighting using markdown fence style."""

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        code = str(self.text).rstrip()
        lang = self.lexer_name if self.lexer_name != "text" else ""
        fence_style = console.get_style("markdown.code.fence", default="none")
        fence_title_style = console.get_style("markdown.code.fence.title", default="none")

        yield Text.assemble(("```", fence_style), (lang, fence_title_style))
        syntax = Syntax(
            code,
            self.lexer_name,
            theme=self.theme,
            word_wrap=True,
            padding=(0, 0),
        )
        yield syntax
        yield Text("```", style=fence_style)


class ThinkingCodeBlock(CodeBlock):
    """A code block for thinking content that uses simple ``` delimiters."""

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        code = str(self.text).rstrip()
        fence_style = "markdown.code.fence"
        code_style = "markdown.code.block"
        lang = self.lexer_name if self.lexer_name != "text" else ""
        yield Text(f"```{lang}", style=fence_style)
        yield Text(code, style=code_style)
        yield Text("```", style=fence_style)


class Divider(MarkdownElement):
    """A horizontal rule with an extra blank line below."""

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        style = console.get_style("markdown.hr", default="none")
        width = min(options.max_width, 100)
        yield Text("-" * width, style=style)


class MarkdownTable(TableElement):
    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        table = Table(
            box=box.MINIMAL,
            show_edge=False,
            border_style=console.get_style("markdown.table.border"),
        )

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
            h2_style = console.get_style("markdown.h2", default="bold")
            text.stylize(h2_style + Style(underline=False))
            yield text
        else:
            yield text


class CheckboxListItem(ListItem):
    """A list item that renders checkbox syntax as Unicode symbols."""

    def render_bullet(self, console: Console, options: ConsoleOptions) -> RenderResult:
        render_options = options.update(width=options.max_width - 3)
        lines = console.render_lines(self.elements, render_options, style=self.style)
        bullet_style = console.get_style("markdown.item.bullet", default="none")

        first_line_text = ""
        if lines:
            first_line_text = "".join(seg.text for seg in lines[0] if seg.text)

        unchecked_match = _CHECKBOX_UNCHECKED_RE.match(first_line_text)
        checked_match = _CHECKBOX_CHECKED_RE.match(first_line_text)

        if unchecked_match:
            bullet = Segment(" \u2610 ", bullet_style)
            skip_chars = len(unchecked_match.group(0))
        elif checked_match:
            checked_style = console.get_style("markdown.checkbox.checked", default="none")
            bullet = Segment(" \u2713 ", checked_style)
            skip_chars = len(checked_match.group(0))
        else:
            bullet = Segment(" \u2022 ", bullet_style)
            skip_chars = 0

        padding = Segment(" " * 3, bullet_style)
        new_line = Segment("\n")

        for first, line in loop_first(lines):
            yield bullet if first else padding
            if first and skip_chars > 0:
                chars_skipped = 0
                for seg in line:
                    if seg.text and chars_skipped < skip_chars:
                        remaining = skip_chars - chars_skipped
                        if len(seg.text) <= remaining:
                            chars_skipped += len(seg.text)
                            continue
                        else:
                            yield Segment(seg.text[remaining:], seg.style)
                            chars_skipped = skip_chars
                    else:
                        yield seg
            else:
                yield from line
            yield new_line


class LocalImageItem(ImageItem):
    """Image element that collects local file paths for external rendering."""

    @classmethod
    def create(cls, markdown: Markdown, token: Token) -> MarkdownElement:
        src = str(token.attrs.get("src", ""))
        instance = cls(src, markdown.hyperlinks)
        if src.startswith("/") and Path(src).exists():
            collected = getattr(markdown, "collected_images", None)
            if collected is not None:
                collected.append(src)
        return instance

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        if self.destination.startswith("/") and Path(self.destination).exists():
            return
        yield from super().__rich_console__(console, options)


class NoInsetMarkdown(Markdown):
    """Markdown with code blocks that have no padding and left-justified headings."""

    elements: ClassVar[dict[str, type[Any]]] = {
        **Markdown.elements,
        "fence": NoInsetCodeBlock,
        "code_block": NoInsetCodeBlock,
        "heading_open": LeftHeading,
        "hr": Divider,
        "table_open": MarkdownTable,
        "html_block": ThinkingHTMLBlock,
        "list_item_open": CheckboxListItem,
        "image": LocalImageItem,
    }

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.collected_images: list[str] = []


class ThinkingMarkdown(Markdown):
    """Markdown for thinking content with grey-styled code blocks and left-justified headings."""

    elements: ClassVar[dict[str, type[Any]]] = {
        **Markdown.elements,
        "fence": ThinkingCodeBlock,
        "code_block": ThinkingCodeBlock,
        "heading_open": LeftHeading,
        "hr": Divider,
        "table_open": MarkdownTable,
        "html_block": ThinkingHTMLBlock,
        "list_item_open": CheckboxListItem,
        "image": LocalImageItem,
    }

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.collected_images: list[str] = []


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
        right_margin: int = 0,
        markdown_class: Callable[..., Markdown] | None = None,
        image_callback: Callable[[str], None] | None = None,
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
            image_callback: Callback to display local images (called with file path)
        """
        self._stable_rendered_lines: list[str] = []
        self._stable_source_line_count: int = 0

        if mdargs:
            self.mdargs: dict[str, Any] = mdargs
        else:
            self.mdargs = {}

        self._live_sink = live_sink
        self._image_callback = image_callback
        self._displayed_images: set[str] = set()

        # Streaming control
        self.when: float = 0.0  # Timestamp of last update
        self.min_delay: float = 1.0 / UI_REFRESH_RATE_FPS
        self._parser: MarkdownIt = MarkdownIt("commonmark")

        self.theme = theme
        self.console = console
        self.left_margin: int = max(left_margin, 0)
        # Default mark "•" when left_margin >= 2 and no mark specified
        self.mark: str | None = mark if mark is not None else ("•" if self.left_margin >= 2 else None)
        self.mark_style: StyleType | None = mark_style

        self.right_margin: int = max(right_margin, 0)
        self.markdown_class: Callable[..., Markdown] = markdown_class or NoInsetMarkdown

    def _get_base_width(self) -> int:
        return self.console.options.max_width

    def _should_use_synchronized_output(self) -> bool:
        if not MARKDOWN_STREAM_SYNCHRONIZED_OUTPUT_ENABLED:
            return False
        if self._live_sink is None:
            return False
        console_file = getattr(self.console, "file", None)
        if console_file is None:
            return False
        isatty = getattr(console_file, "isatty", None)
        if isatty is None:
            return False
        return bool(isatty())

    @contextlib.contextmanager
    def _synchronized_output(self) -> Any:
        """Batch terminal updates to reduce flicker.

        Uses xterm's "Synchronized Output" mode (DECSET/DECRST 2026). Terminals that
        don't support it will typically ignore the escape codes.
        """

        if not self._should_use_synchronized_output():
            yield
            return

        console_file = self.console.file
        enabled = False
        try:
            console_file.write("\x1b[?2026h")
            flush = getattr(console_file, "flush", None)
            if flush is not None:
                flush()
            enabled = True
        except Exception:
            pass

        try:
            yield
        finally:
            if enabled:
                with contextlib.suppress(Exception):
                    console_file.write("\x1b[?2026l")
                    flush = getattr(console_file, "flush", None)
                    if flush is not None:
                        flush()

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

        # When the buffer ends mid-line, markdown-it-py can temporarily classify
        # some lines as a thematic break (hr). For example, a trailing "- --"
        # parses as an hr, but appending a non-hr character ("- --0") turns it
        # into a list item, which should belong to the previous list block.
        #
        # Because stable_line is clamped to be monotonic, advancing to the hr's
        # start line would be irreversible and can split a list across
        # stable/live, producing a render mismatch.
        if last.type == "hr" and not text.endswith("\n"):
            prev = top_level[-2]
            assert prev.map is not None
            return max(prev.map[0], 0)

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

        # If the "stable" prefix is only whitespace and we haven't stabilized any
        # non-whitespace content yet, keep everything in the live buffer.
        #
        # This avoids cases where marks/indentation should apply to the first
        # visible line, but would be suppressed because stable_line > 0.
        if min_stable_line == 0 and stable_source.strip() == "":
            return "", text, 0
        return stable_source, live_source, stable_line

    def render_stable_ansi(self, stable_source: str, *, has_live_suffix: bool, final: bool) -> tuple[str, list[str]]:
        """Render stable prefix to ANSI, preserving inter-block spacing.

        Returns:
            tuple: (ANSI string, collected local image paths)
        """
        if not stable_source:
            return "", []

        render_source = stable_source
        if not final and has_live_suffix:
            render_source = self._append_nonfinal_sentinel(stable_source)

        lines, images = self._render_markdown_to_lines(render_source, apply_mark=True)
        return "".join(lines), images

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

    def _render_markdown_to_lines(self, text: str, *, apply_mark: bool) -> tuple[list[str], list[str]]:
        """Render markdown text to a list of lines.

        Args:
            text (str): Markdown text to render

        Returns:
            tuple: (lines with line endings preserved, collected local image paths)
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

        collected_images = getattr(markdown, "collected_images", [])

        lines = output.splitlines(keepends=True)
        use_mark = apply_mark and bool(self.mark) and self.left_margin >= 2

        # Fast path: no margin, no mark -> just rstrip each line
        if self.left_margin == 0 and not use_mark:
            processed_lines = [line.rstrip() + "\n" if line.endswith("\n") else line.rstrip() for line in lines]
            return processed_lines, list(collected_images)

        indent_prefix = " " * self.left_margin
        processed_lines: list[str] = []
        mark_applied = False

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
            else:
                stripped = indent_prefix + stripped

            if line.endswith("\n"):
                stripped += "\n"
            processed_lines.append(stripped)

        return processed_lines, list(collected_images)

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

        stable_chunk_to_print: str | None = None
        new_images: list[str] = []
        stable_changed = final or stable_line > self._stable_source_line_count
        if stable_changed and stable_source:
            stable_ansi, collected_images = self.render_stable_ansi(
                stable_source, has_live_suffix=bool(live_source), final=final
            )
            stable_lines = stable_ansi.splitlines(keepends=True)
            new_lines = stable_lines[len(self._stable_rendered_lines) :]
            if new_lines:
                stable_chunk_to_print = "".join(new_lines)
            self._stable_rendered_lines = stable_lines
            self._stable_source_line_count = stable_line
            for img in collected_images:
                if img not in self._displayed_images:
                    new_images.append(img)
                    self._displayed_images.add(img)
        elif final and not stable_source:
            self._stable_rendered_lines = []
            self._stable_source_line_count = stable_line

        live_text_to_set: Text | None = None
        if not final and MARKDOWN_STREAM_LIVE_REPAINT_ENABLED and self._live_sink is not None:
            # When nothing is stable yet, we still want to show incremental output.
            # Apply the mark only for the first (all-live) frame so it stays anchored
            # to the first visible line of the full message.
            apply_mark_to_live = stable_line == 0
            live_lines, _ = self._render_markdown_to_lines(live_source, apply_mark=apply_mark_to_live)

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

            live_text_to_set = Text.from_ansi("".join(live_lines))

        with self._synchronized_output():
            # Update/clear live area first to avoid blank padding when stable block appears
            if final:
                if self._live_sink is not None:
                    self._live_sink(None)
            elif live_text_to_set is not None and self._live_sink is not None:
                self._live_sink(live_text_to_set)

            if stable_chunk_to_print:
                self.console.print(Text.from_ansi(stable_chunk_to_print), end="\n")

            if new_images and self._image_callback:
                for img_path in new_images:
                    self._image_callback(img_path)

        elapsed = time.time() - start
        self.min_delay = min(max(elapsed * 6, 1.0 / 30), 0.5)
