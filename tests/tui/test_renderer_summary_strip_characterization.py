"""Characterization tests for renderer summary-tag stripping + pure helpers.

The summary-tag stripping logic is duplicated across
``TUICommandRenderer.display_compaction_summary`` (~line 736) and
``display_handoff`` (~line 824). These tests lock in the observable rendered
output so that de-duplicating (extracting a shared helper) is provably
behavior-preserving.

Also covers the small pure static helpers on the renderer.
"""

from __future__ import annotations

import asyncio
import io

from rich.console import Console
from rich.text import Text

from klaude_code.tui.commands import (
    DynamicSeparatorText,
    RenderCompactionSummary,
    RenderHandoff,
    SpinnerStatusLine,
)
from klaude_code.tui.renderer import TUICommandRenderer


def _renderer_and_output() -> tuple[TUICommandRenderer, io.StringIO]:
    renderer = TUICommandRenderer()
    output = io.StringIO()
    renderer.console = Console(file=output, theme=renderer.themes.app_theme, width=100, force_terminal=False)
    renderer.console.push_theme(renderer.themes.markdown_theme)
    return renderer, output


# ---------------------------------------------------------------------------
# Summary-tag stripping (compaction summary)
# ---------------------------------------------------------------------------


def test_compaction_summary_strips_summary_and_file_tags() -> None:
    renderer, output = _renderer_and_output()
    summary = "<summary>Did some work.</summary>\n<read_files>a.py</read_files>\n<modified-files>b.py</modified-files>"
    asyncio.run(renderer.execute([RenderCompactionSummary(summary=summary)]))

    rendered = output.getvalue()
    # The XML-ish wrapper tags are stripped from display.
    assert "<summary>" not in rendered
    assert "</summary>" not in rendered
    assert "<read_files>" not in rendered
    assert "</read_files>" not in rendered
    assert "<modified-files>" not in rendered
    assert "</modified-files>" not in rendered
    # Inner content survives and the header is rendered.
    assert "Did some work." in rendered
    assert "Context Compacted" in rendered


def test_compaction_summary_blank_summary_renders_nothing() -> None:
    renderer, output = _renderer_and_output()
    asyncio.run(renderer.execute([RenderCompactionSummary(summary="   \n  ")]))
    assert output.getvalue() == ""


def test_compaction_summary_kept_items_brief_listed() -> None:
    renderer, output = _renderer_and_output()
    asyncio.run(
        renderer.execute(
            [
                RenderCompactionSummary(
                    summary="<summary>work</summary>",
                    kept_items_brief=(("Bash", 2, "pwd"), ("Read", 1, "file")),
                )
            ]
        )
    )
    rendered = output.getvalue()
    assert "Kept uncompacted" in rendered
    assert "Bash x 2" in rendered
    assert "Read" in rendered


# ---------------------------------------------------------------------------
# Summary-tag stripping (handoff) -- the duplicated logic
# ---------------------------------------------------------------------------


def test_handoff_strips_summary_tags() -> None:
    renderer, output = _renderer_and_output()
    summary = "<summary>Handoff details here.</summary>"
    asyncio.run(renderer.execute([RenderHandoff(summary=summary)]))

    rendered = output.getvalue()
    assert "<summary>" not in rendered
    assert "</summary>" not in rendered
    assert "Handoff details here." in rendered


def test_handoff_blank_summary_still_renders_header() -> None:
    # Unlike compaction summary, handoff has no early-return on blank input:
    # it always renders the "Context Handed Off" header rule.
    renderer, output = _renderer_and_output()
    asyncio.run(renderer.execute([RenderHandoff(summary="  ")]))
    assert "Context Handed Off" in output.getvalue()


# ---------------------------------------------------------------------------
# Pure static helpers
# ---------------------------------------------------------------------------


def test_resolve_separator_text_none() -> None:
    assert TUICommandRenderer._resolve_separator_text(None) is None


def test_resolve_separator_text_plain_string() -> None:
    assert TUICommandRenderer._resolve_separator_text("---") == "---"


def test_resolve_separator_text_dynamic() -> None:
    dyn = DynamicSeparatorText(factory=lambda: "computed")
    assert TUICommandRenderer._resolve_separator_text(dyn) == "computed"


def test_resolve_separator_text_dynamic_returning_none() -> None:
    dyn = DynamicSeparatorText(factory=lambda: None)
    assert TUICommandRenderer._resolve_separator_text(dyn) is None


def test_spinner_text_key_for_plain_string() -> None:
    assert TUICommandRenderer._spinner_text_key("hello") == ("str", "hello")


def test_spinner_text_key_for_text() -> None:
    assert TUICommandRenderer._spinner_text_key(Text("hi")) == ("Text", "hi", "")


def test_spinner_text_key_distinguishes_str_and_text() -> None:
    assert TUICommandRenderer._spinner_text_key("hi") != TUICommandRenderer._spinner_text_key(Text("hi"))


def test_spinner_right_text_key_none() -> None:
    assert TUICommandRenderer._spinner_right_text_key(None) == ("none",)


def test_spinner_right_text_key_str_and_text() -> None:
    assert TUICommandRenderer._spinner_right_text_key("x") == ("str", "x")
    assert TUICommandRenderer._spinner_right_text_key(Text("y")) == ("Text", "y", "")


def test_spinner_status_line_dataclass_defaults() -> None:
    line = SpinnerStatusLine(text="hi")
    assert line.session_id is None
    assert line.text == "hi"
