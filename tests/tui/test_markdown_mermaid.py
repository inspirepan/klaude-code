"""Mermaid fences inside NoInsetMarkdown / ThinkingMarkdown / MarkdownStream."""

from __future__ import annotations

import io
import re

import pytest
from rich.console import Console
from rich.text import Text

from klaude_code.tui.components.rich import markdown as markdown_module
from klaude_code.tui.components.rich.markdown import MarkdownStream, NoInsetMarkdown, ThinkingMarkdown

_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")

GRAPH_FENCE = "```mermaid\ngraph TD\n A[Start] --> B[End]\n```\n"


def _render(markdown: NoInsetMarkdown | ThinkingMarkdown, *, width: int = 80) -> str:
    buffer = io.StringIO()
    console = Console(file=buffer, force_terminal=False, width=width)
    console.print(markdown)
    return buffer.getvalue()


def test_mermaid_fence_renders_box_art() -> None:
    out = _render(NoInsetMarkdown(GRAPH_FENCE, code_theme="monokai"))
    assert "▼" in out
    assert "│ Start │" in out
    assert "│ End │" in out
    assert "graph TD" not in out


def test_mermaid_fence_in_live_tail_stays_a_code_block() -> None:
    out = _render(NoInsetMarkdown(GRAPH_FENCE, code_theme="monokai", live_tail=True))
    assert "graph TD" in out
    assert "▼" not in out


def test_thinking_markdown_renders_mermaid_fence() -> None:
    out = _render(ThinkingMarkdown(GRAPH_FENCE, code_theme="monokai"))
    assert "▼" in out
    assert "graph TD" not in out


def test_unsupported_mermaid_type_falls_back_to_framed_source() -> None:
    out = _render(NoInsetMarkdown("```mermaid\ngantt\n title Plan\n```\n", code_theme="monokai"))
    assert "mermaid: gantt" in out
    assert "title Plan" in out


def test_mermaid_too_wide_for_console_falls_back() -> None:
    fence = (
        "```mermaid\nflowchart LR\n A[aaaaaaaaaaaaaaaaaaaa] --> B[bbbbbbbbbbbbbbbbbbbb] --> C[cccccccccccccccc]\n```\n"
    )
    out = _render(NoInsetMarkdown(fence, code_theme="monokai"), width=40)
    assert "mermaid: flowchart" in out
    assert "too wide" in out
    assert all(len(line) <= 40 for line in out.splitlines())


def test_renderer_failure_falls_back_to_plain_code_block(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("layout exploded")

    monkeypatch.setattr(markdown_module, "render_mermaid", boom)
    out = _render(NoInsetMarkdown(GRAPH_FENCE, code_theme="monokai"))
    assert "graph TD" in out
    assert "▼" not in out


def test_other_languages_are_untouched() -> None:
    out = _render(NoInsetMarkdown("```python\nprint(1)\n```\n", code_theme="monokai"))
    assert "print(1)" in out


def test_stream_keeps_source_live_then_draws_art_when_stable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(markdown_module, "MARKDOWN_STREAM_LIVE_REPAINT_ENABLED", True)
    live_calls: list[object] = []

    def _sink(renderable: object) -> None:
        live_calls.append(renderable)

    buffer = io.StringIO()
    console = Console(file=buffer, force_terminal=True, width=80)
    stream = MarkdownStream(console=console, live_sink=_sink, left_margin=2, mark=">")

    partial = "Intro paragraph.\n\n```mermaid\ngraph TD\n A[Start] --> B[End]\n"
    stream.update(partial)
    assert live_calls, "live area should show the streaming fence"
    last_live = live_calls[-1]
    assert isinstance(last_live, Text)
    assert "graph TD" in last_live.plain
    assert "▼" not in last_live.plain

    stream.update(partial + "```\n", final=True)
    scrollback = _ANSI_ESCAPE_RE.sub("", buffer.getvalue())
    assert "Intro paragraph." in scrollback
    assert "▼" in scrollback
    assert "│ Start │" in scrollback
    assert "graph TD" not in scrollback
