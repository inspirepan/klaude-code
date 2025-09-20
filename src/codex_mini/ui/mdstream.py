# copy from https://github.com/Aider-AI/aider/blob/main/aider/mdstream.py
import re
import time
from types import TracebackType
from typing import Any, ClassVar

from rich.console import Console, ConsoleOptions, Group, RenderResult, RenderableType
from rich.live import Live
from rich.markdown import CodeBlock, Heading, Markdown
from rich.rule import Rule
from rich.spinner import Spinner
from rich.style import Style
from rich.syntax import Syntax
from rich.text import Text
from rich.theme import Theme

_H2_RE = re.compile(r"^##(?!#)(?:\s+|$)")
_CODE_FENCE_PREFIXES = {"```", "~~~"}


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
    """A tool for streaming markdown rendering by h2 headings.

    Always uses a Live window to display the current paragraph during streaming output.
    When a new h2 heading is detected, the previous paragraph is fixed to the console,
    and a new Live is started for the next paragraph."""

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
        self.mdargs: dict[str, Any] = dict(mdargs) if mdargs else {}

        self.theme = theme
        self.console = console or Console(theme=theme)

        # Live management
        self.live: Live | None = None
        self.spinner = spinner

        # Segment management
        self.completed_segments: list[str] = []
        self.when: float = 0.0
        self.min_delay: float = 1.0 / 20

    def _split_segments(self, text: str) -> list[str]:
        """Split markdown into semantic segments by h2 headings."""

        if not text:
            return []

        lines = text.splitlines(keepends=True)
        segments: list[str] = []
        current: list[str] = []
        in_code_block = False

        def flush() -> None:
            if current:
                segments.append("".join(current))
                current.clear()

        for line in lines:
            stripped = line.lstrip()
            fence = stripped[:3]
            if fence in _CODE_FENCE_PREFIXES:
                in_code_block = not in_code_block
                current.append(line)
                continue

            if not in_code_block and _H2_RE.match(stripped):
                flush()
                current.append(line)
            else:
                current.append(line)

        flush()

        return segments

    def _start_live(self, renderable: RenderableType) -> None:
        if self.live is not None:
            return
        self.live = Live(
            renderable,
            refresh_per_second=1.0 / self.min_delay,
            console=self.console,
            transient=True,
        )
        self.live.start()

    def _stop_live(self) -> None:
        if self.live is None:
            return
        live = self.live
        self.live = None
        try:
            live.stop()
        except Exception:
            pass

    def _render_markdown(self, text: str) -> RenderableType:
        return NoInsetMarkdown(text, **self.mdargs) if text.strip() else Text()

    def _live_renderable(self, text: str, final: bool) -> RenderableType:
        markdown_renderable = self._render_markdown(text)
        if self.spinner and not final:
            return Group(markdown_renderable, Text(), self.spinner)
        return markdown_renderable

    def _finalize_segment(self, text: str) -> None:
        self._stop_live()
        renderable: RenderableType = self._render_markdown(text)
        self.console.print(renderable)
        self.console.print()
        self.completed_segments.append(text)

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    def close(self) -> None:
        self._stop_live()

    def __enter__(self) -> "MarkdownStream":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool | None:
        self.close()
        return None

    def update(self, text: str, final: bool = False) -> None:
        """Update rendering state based on current content.

        Args:
            text: Full markdown content received so far.
            final: If True, indicates content is finished and Live should be closed.
        """
        now = time.time()
        if not final and now - self.when < self.min_delay:
            return
        self.when = now

        segments = self._split_segments(text)

        if not segments:
            if final:
                self._stop_live()
            elif self.live is not None:
                self.live.update(self._live_renderable("", final))
            return

        finalized_count = len(segments) if final else max(len(segments) - 1, 0)
        for idx in range(finalized_count):
            if idx < len(self.completed_segments):
                continue
            segment_text = segments[idx]
            self._finalize_segment(segment_text)

        has_active_segment = finalized_count < len(segments)
        if has_active_segment:
            active_text = segments[finalized_count]
            renderable = self._live_renderable(active_text, final)
            if self.live is None:
                self._start_live(renderable)
            else:
                self.live.update(renderable)
        else:
            if final:
                self._stop_live()
