from __future__ import annotations

import contextlib
import io
import re
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, ClassVar

from markdown_it import MarkdownIt
from markdown_it.token import Token
from prompt_toolkit.patch_stdout import StdoutProxy
from rich import box
from rich._loop import loop_first
from rich.console import Console, ConsoleOptions, RenderableType, RenderResult
from rich.markdown import CodeBlock, Heading, ImageItem, ListItem, Markdown, MarkdownElement, TableElement
from rich.panel import Panel
from rich.segment import Segment
from rich.style import Style, StyleType
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text
from rich.theme import Theme

from klaude_code.const import (
    MARKDOWN_STREAM_ADAPTIVE_DELAY_CHARS,
    MARKDOWN_STREAM_LIVE_REPAINT_ENABLED,
    MARKDOWN_STREAM_MAX_DELAY_S,
    MARKDOWN_STREAM_SYNCHRONIZED_OUTPUT_ENABLED,
    UI_REFRESH_RATE_FPS,
)
from klaude_code.tui.components.rich.mermaid import MermaidStyles
from klaude_code.tui.components.rich.mermaid import render as render_mermaid

_THINKING_HTML_BLOCK_RE = re.compile(
    r"\A\s*<thinking>\s*\n?(?P<body>.*?)(?:\n\s*)?</thinking>\s*\Z",
    flags=re.IGNORECASE | re.DOTALL,
)

_HTML_COMMENT_BLOCK_RE = re.compile(r"\A\s*<!--.*?-->\s*\Z", flags=re.DOTALL)

_CHECKBOX_UNCHECKED_RE = re.compile(r"^\[ \]\s*")
_CHECKBOX_CHECKED_RE = re.compile(r"^\[x\]\s*", re.IGNORECASE)
_ORDERED_LIST_LINE_RE = re.compile(r"^\s{0,3}\d+[.)]\s+.+")
_ORDERED_LIST_MARKER_PREFIX_RE = re.compile(r"^\s{0,3}\d{1,9}\s*$")
_LOCAL_IMAGE_MARKDOWN_LINE_RE = re.compile(r"^\s*!\[[^\]]*\]\((?P<path>/[^)]+)\)\s*$")

# Zero-width stamp LeftHeading puts at the start of every heading so
# SectionIndentMarkdown can tell heading lines from body lines once the document
# has been rendered to segments. It is stripped before anything is yielded.
_HEADING_STAMP = "​"
# Marker hung off each heading. The right-pointing triangle separates a section
# mark from the round mark on the message as a whole.
HEADING_MARK = "▶"
SECTION_INDENT = 2


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


def _code_block_panel(console: Console, body: RenderableType, lang: str) -> Panel:
    """Frame a code block in a panel, with the language as its left-aligned title.

    expand=False keeps the panel as narrow as the longest line.
    """

    title = Text(lang, style=console.get_style("markdown.code.fence.title", default="none")) if lang else None
    return Panel(
        body,
        title=title,
        title_align="left",
        box=box.ROUNDED,
        border_style=console.get_style("markdown.code.border", default="none"),
        expand=False,
    )


def _mermaid_styles(console: Console) -> MermaidStyles:
    def style(name: str) -> Style:
        return console.get_style(name, default="none")

    return MermaidStyles(
        border=style("markdown.mermaid.border"),
        node_text=style("markdown.mermaid.node"),
        edge=style("markdown.mermaid.edge"),
        edge_label=style("markdown.mermaid.edge.label"),
        title=style("markdown.mermaid.title"),
    )


def _render_mermaid_block(console: Console, options: ConsoleOptions, code: str) -> Text | None:
    """Draw a ```mermaid fence as box art; None when the block is blank or the renderer fails."""

    try:
        art = render_mermaid(code, _mermaid_styles(console), options.max_width)
    except Exception:
        return None
    if art is None:
        return None
    lines = art.styled_lines
    # Layout rounding can leave an empty first or last row; drop it.
    while lines and not lines[0].plain.strip():
        lines = lines[1:]
    while lines and not lines[-1].plain.strip():
        lines = lines[:-1]
    if not lines:
        return None
    return Text("\n", no_wrap=True).join(lines)


class MermaidAwareCodeBlock(CodeBlock):
    """A code block that draws ```mermaid fences as box art once they are stable.

    While the fence is still streaming (`live_tail`) it stays a plain code block,
    so the diagram is laid out once when the block lands in scrollback instead of
    on every live-area repaint.
    """

    live_tail: bool = False

    @classmethod
    def create(cls, markdown: Markdown, token: Token) -> MermaidAwareCodeBlock:
        node_info = token.info or ""
        lexer_name = node_info.partition(" ")[0]
        block = cls(lexer_name or "text", markdown.code_theme)
        block.live_tail = bool(getattr(markdown, "live_tail", False))
        return block

    def _mermaid_art(self, console: Console, options: ConsoleOptions, code: str) -> Text | None:
        if self.lexer_name.lower() != "mermaid" or self.live_tail:
            return None
        return _render_mermaid_block(console, options, code)


class NoInsetCodeBlock(MermaidAwareCodeBlock):
    """A code block with syntax highlighting, framed in a panel instead of ``` markers."""

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        code = str(self.text).rstrip()
        # Skip empty code blocks — these appear in the live streaming area when only
        # the opening fence has arrived yet, producing a spurious empty block.
        if not code:
            return
        art = self._mermaid_art(console, options, code)
        if art is not None:
            yield art
            return
        try:
            body: RenderableType = Syntax(
                code,
                self.lexer_name,
                theme=self.theme,
                word_wrap=True,
                padding=(0, 0),
            )
        except Exception:
            # Fallback to plain text if the pygments lexer is unavailable.
            body = Text(code)
        yield _code_block_panel(console, body, self.lexer_name if self.lexer_name != "text" else "")


class ThinkingCodeBlock(MermaidAwareCodeBlock):
    """A code block for thinking content, framed in a panel with no syntax highlighting."""

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        code = str(self.text).rstrip()
        if not code:
            return
        art = self._mermaid_art(console, options, code)
        if art is not None:
            yield art
            return
        body = Text(code, style="markdown.code.block")
        yield _code_block_panel(console, body, self.lexer_name if self.lexer_name != "text" else "")


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


def _stamp_heading(text: Text) -> Text:
    """Prefix a heading with the zero-width stamp SectionIndentMarkdown looks for."""

    stamped = Text(_HEADING_STAMP, justify="left")
    stamped.append_text(text)
    return stamped


class LeftHeading(Heading):
    """A heading class that renders left-justified."""

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        text = self.text
        text.justify = "left"  # Override justification
        if self.tag == "h1":
            text = text.assemble((" ", "markdown.h1"), text, (" ", "markdown.h1"))
        elif self.tag == "h2":
            text.stylize(console.get_style("markdown.h2", default="bold"))
            # Extra breathing room above each section.
            yield Text("")
        yield _stamp_heading(text)


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

    def __init__(self, destination: str, hyperlinks: bool, alt_text: str = "") -> None:
        super().__init__(destination, hyperlinks)
        self._alt_text = alt_text

    @classmethod
    def create(cls, markdown: Markdown, token: Token) -> MarkdownElement:
        src = str(token.attrs.get("src", ""))
        alt_text = token.content or ""
        instance = cls(src, markdown.hyperlinks, alt_text)
        if src.startswith("/") and Path(src).exists():
            collected = getattr(markdown, "collected_images", None)
            if collected is not None:
                collected.append((src, alt_text))
        return instance

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        if self.destination.startswith("/") and Path(self.destination).exists():
            yield Text(f"![{self._alt_text}]({self.destination})", style="markdown.image.placeholder")
            return
        yield from super().__rich_console__(console, options)


class SectionIndentMarkdown(Markdown):
    """Markdown that hangs a bullet off every heading and indents its section.

    Content before the first heading keeps the caller's own indentation, so a
    reply that opens with a paragraph still sits tight against the message mark.
    Documents without a heading render exactly as Rich would.

    `inside_section` tells a partial render (the live tail of a stream) that a
    heading already appeared in the part rendered before it. `live_tail` marks
    that partial render itself; elements such as mermaid fences use it to skip
    work that only pays off once the block is stable.
    """

    def __init__(self, *args: Any, inside_section: bool = False, live_tail: bool = False, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.collected_images: list[tuple[str, str]] = []
        self._inside_section = inside_section
        self.live_tail = live_tail

    def _render_segments(self, console: Console, options: ConsoleOptions) -> Iterator[Segment]:
        for item in super().__rich_console__(console, options):
            if isinstance(item, Segment):
                yield item
            else:
                yield from console.render(item, options)

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        in_section = self._inside_section
        if not in_section and not any(token.type == "heading_open" for token in self.parsed):
            yield from super().__rich_console__(console, options)
            return

        # Reserve the indent up front so every line wraps at the same column,
        # whether or not it ends up inside a section.
        inner = options.update_width(max(options.max_width - SECTION_INDENT, 1))
        heading_mark = Segment(f"{HEADING_MARK} ", console.get_style("markdown.heading.mark", default="none"))
        indent = Segment(" " * SECTION_INDENT)

        for line in Segment.split_lines(self._render_segments(console, inner)):
            if any(_HEADING_STAMP in segment.text for segment in line):
                in_section = True
                yield heading_mark
                for segment in line:
                    yield Segment(segment.text.replace(_HEADING_STAMP, ""), segment.style, segment.control)
            else:
                if in_section and any(segment.text.strip() for segment in line):
                    yield indent
                yield from line
            yield Segment.line()


class NoInsetMarkdown(SectionIndentMarkdown):
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


class ThinkingMarkdown(SectionIndentMarkdown):
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
        image_callback: Callable[[str, str | None], None] | None = None,
        scrollback_write_sink: Callable[[], None] | None = None,
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
            image_callback: Callback to display local images (called with file path and optional caption)
            scrollback_write_sink: Callback invoked before stable content is written to scrollback
        """
        self._stable_rendered_lines: list[str] = []
        self._stable_source_line_count: int = 0
        # Once the stable prefix holds a heading, the live tail is inside that
        # heading's section and must be indented to match.
        self._stable_has_heading: bool = False

        if mdargs:
            self.mdargs: dict[str, Any] = mdargs
        else:
            self.mdargs = {}

        self._live_sink = live_sink
        self._image_callback = image_callback
        self._scrollback_write_sink = scrollback_write_sink
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

    def _effective_min_delay(self, text_length: int) -> float:
        """Frame interval scaled by buffer size to bound full-buffer parse cost."""
        scale = max(1.0, text_length / MARKDOWN_STREAM_ADAPTIVE_DELAY_CHARS)
        return min(self.min_delay * scale, MARKDOWN_STREAM_MAX_DELAY_S)

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
        # When stdout is patched (interactive REPL), writes are queued and
        # re-emitted later inside the proxy's own DEC-2026 frame around its
        # erase/write/redraw cycle. DEC modes do not nest: an embedded ?2026l
        # would end that frame right after the erase, presenting the terminal
        # a frame without the bottom prompt UI — the exact flicker the proxy
        # exists to prevent. Let the proxy own synchronization in that case.
        if isinstance(console_file, StdoutProxy):
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
        if not top_level:
            return 0

        last = top_level[-1]
        assert last.map is not None

        list_item_stable_line = self._compute_list_item_stable_line(tokens, last)
        if list_item_stable_line > 0:
            return list_item_stable_line

        if len(top_level) < 2:
            return 0

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

        # Similar mid-line reclassification can happen after ordered lists.
        #
        # Example while streaming:
        #   9. a
        #
        #   4
        #
        # The trailing "4" is parsed as a paragraph in the current frame, so the
        # previous ordered_list block looks complete and would be stabilized.
        # When more text arrives ("4. b"), markdown-it merges it into the same
        # ordered list, which mutates already-rendered stable lines.
        #
        # Guard this by keeping the prior list block live when the final line is
        # an incomplete ordered-list marker prefix.
        if not text.endswith("\n") and len(top_level) >= 2 and last.type == "paragraph_open":
            prev = top_level[-2]
            assert prev.map is not None
            if prev.type == "ordered_list_open":
                trailing_line = text.rsplit("\n", 1)[-1]
                if _ORDERED_LIST_MARKER_PREFIX_RE.match(trailing_line):
                    return max(prev.map[0], 0)

        start_line = last.map[0]
        return max(start_line, 0)

    def _compute_list_item_stable_line(self, tokens: list[Token], list_token: Token) -> int:
        if list_token.type not in {"bullet_list_open", "ordered_list_open"} or list_token.map is None:
            return 0

        list_start, list_end = list_token.map
        top_level_items = [
            token
            for token in tokens
            if token.type == "list_item_open"
            and token.level == list_token.level + 1
            and token.map is not None
            and list_start <= token.map[0] < list_end
        ]
        if len(top_level_items) < 2:
            return 0

        last_item = top_level_items[-1]
        assert last_item.map is not None
        return max(last_item.map[0], 0)

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

    def render_stable_ansi(
        self, stable_source: str, *, has_live_suffix: bool, final: bool
    ) -> tuple[str, list[tuple[str, str]]]:
        """Render stable prefix to ANSI, preserving inter-block spacing.

        Returns:
            tuple: (ANSI string, collected local image paths)
        """
        if not stable_source:
            return "", []

        render_source = stable_source
        if not final and has_live_suffix and not self._stable_prefix_ends_inside_list(stable_source):
            render_source = self._append_nonfinal_sentinel(stable_source)

        lines, images = self._render_markdown_to_lines(render_source, apply_mark=True)
        return "".join(lines), images

    def _stable_prefix_ends_inside_list(self, stable_source: str) -> bool:
        stable_line = len(stable_source.splitlines(keepends=True))
        if stable_line == 0:
            return False

        try:
            tokens = self._parser.parse(stable_source)
        except Exception:
            return False

        list_tokens = [
            token
            for token in tokens
            if token.type in {"bullet_list_open", "ordered_list_open"} and token.level == 0 and token.map is not None
        ]
        if not list_tokens:
            return False

        last_list = list_tokens[-1]
        assert last_list.map is not None
        return last_list.map[1] == stable_line

    def _source_has_heading(self, source: str) -> bool:
        try:
            tokens = self._parser.parse(source)
        except Exception:  # markdown-it-py may raise various internal errors during parsing
            return False
        return any(token.type == "heading_open" for token in tokens)

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

    def _render_markdown_to_lines(
        self, text: str, *, apply_mark: bool, inside_section: bool = False, live_tail: bool = False
    ) -> tuple[list[str], list[tuple[str, str]]]:
        """Render markdown text to a list of lines.

        Args:
            text (str): Markdown text to render
            inside_section (bool): True when a heading appeared before this chunk
            live_tail (bool): True when rendering the still-streaming last block

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

        markdown = self.markdown_class(
            self._normalize_ordered_list_local_image_spacing(text),
            inside_section=inside_section,
            live_tail=live_tail,
            **self.mdargs,
        )
        temp_console.print(markdown)
        output = string_io.getvalue()

        collected_images = getattr(markdown, "collected_images", [])

        lines = output.splitlines(keepends=True)
        if apply_mark:
            while lines and not lines[0].strip():
                lines.pop(0)
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

    def _normalize_ordered_list_local_image_spacing(self, text: str) -> str:
        if "![" not in text:
            return text

        lines = text.splitlines()
        if not lines:
            return text

        had_trailing_newline = text.endswith("\n")
        normalized: list[str] = []

        for index, line in enumerate(lines):
            stripped = line.strip()
            image_match = _LOCAL_IMAGE_MARKDOWN_LINE_RE.match(stripped)
            if image_match is None:
                normalized.append(line)
                continue

            path = image_match.group("path")
            if not Path(path).exists():
                normalized.append(line)
                continue

            prev_nonempty = next((candidate for candidate in reversed(normalized) if candidate.strip()), "")
            next_nonempty = next((candidate for candidate in lines[index + 1 :] if candidate.strip()), "")
            adjacent_ordered = _ORDERED_LIST_LINE_RE.match(prev_nonempty) or _ORDERED_LIST_LINE_RE.match(next_nonempty)
            if not adjacent_ordered:
                normalized.append(line)
                continue

            if normalized and normalized[-1].strip():
                normalized.append("")
            normalized.append(line)

            has_next_content = index + 1 < len(lines) and bool(lines[index + 1].strip())
            if has_next_content:
                normalized.append("")

        result = "\n".join(normalized)
        if had_trailing_newline:
            result += "\n"
        return result

    def __del__(self) -> None:
        """Destructor to ensure Live display is properly cleaned up."""
        if self._live_sink is None:
            return
        with contextlib.suppress(Exception):
            self._live_sink(None)

    def update(self, text: str, final: bool = False) -> None:
        """Update the display with the latest full markdown buffer."""

        now = time.time()
        if not final and now - self.when < self._effective_min_delay(len(text)):
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
        new_images: list[tuple[str, str]] = []
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
            self._stable_has_heading = self._stable_has_heading or self._source_has_heading(stable_source)
            for img_path, img_alt in collected_images:
                if img_path not in self._displayed_images:
                    new_images.append((img_path, img_alt))
                    self._displayed_images.add(img_path)
        elif final and not stable_source:
            self._stable_rendered_lines = []
            self._stable_source_line_count = stable_line

        live_text_to_set: Text | None = None
        if not final and MARKDOWN_STREAM_LIVE_REPAINT_ENABLED and self._live_sink is not None:
            # Only update the live area after we have rendered at least one stable block.
            #
            # This keeps the bottom "live" region anchored to stable scrollback, and
            # avoids showing a live frame that would later need to be retroactively
            # re-rendered once stable content exists.
            if not self._stable_rendered_lines:
                return
            # When nothing is stable yet, we still want to show incremental output.
            # Apply the mark only for the first (all-live) frame so it stays anchored
            # to the first visible line of the full message.
            apply_mark_to_live = stable_line == 0
            live_lines, _ = self._render_markdown_to_lines(
                live_source,
                apply_mark=apply_mark_to_live,
                inside_section=self._stable_has_heading,
                live_tail=True,
            )

            if self._stable_rendered_lines:
                if stable_source.endswith("\n\n"):
                    while live_lines and not live_lines[0].strip():
                        live_lines = live_lines[1:]

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
                if self._scrollback_write_sink is not None:
                    self._scrollback_write_sink()
                end = "\n" if stable_chunk_to_print.endswith("\n") else ""
                stable_text = stable_chunk_to_print[:-1] if end else stable_chunk_to_print
                self.console.print(Text.from_ansi(stable_text), end=end)

            if new_images and self._image_callback:
                for img_path, img_alt in new_images:
                    caption = img_alt.strip() or None
                    self._image_callback(img_path, caption)

        elapsed = time.time() - start
        self.min_delay = min(max(elapsed * 6, 1.0 / 30), 0.5)
