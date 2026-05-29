"""Characterization tests for ``export_session_html``.

These golden-assert key structural parts of the rendered HTML so that
extracting the inline CSS / JS into asset files (or otherwise refactoring the
~1600-line module) can be proven behavior-preserving. They assert what the
current output IS, not what it should be.

Pure helper functions (``_text_preview``, ``_usage_summary``, etc.) are also
locked in directly -- these are the cheapest, most stable contracts.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from klaude_code.protocol import llm_param, message
from klaude_code.session.session import Session
from klaude_code.tui.command import export_session_html as esh
from klaude_code.tui.command.export_session_html import render_session_export_html

pytestmark = pytest.mark.usefixtures("isolated_home")


# ---------------------------------------------------------------------------
# Full-document golden structure
# ---------------------------------------------------------------------------


def _build_session(work_dir: Path) -> Session:
    session = Session.create(work_dir=work_dir)
    session.title = "Golden Export"
    session.conversation_history = [
        message.UserMessage(parts=message.text_parts_from_str("hello **world**")),
        message.AssistantMessage(
            parts=[
                message.ThinkingTextPart(text="checking the repo"),
                message.TextPart(text="Implemented the feature."),
                message.ToolCallPart(call_id="call_1", tool_name="Bash", arguments_json='{"command":"pwd"}'),
            ]
        ),
        message.ToolResultMessage(
            call_id="call_1",
            tool_name="Bash",
            status="success",
            output_text=str(work_dir),
        ),
        message.DeveloperMessage(parts=message.text_parts_from_str("<system-reminder>Checkpoint 1</system-reminder>")),
    ]
    return session


def _tools() -> list[llm_param.ToolSchema]:
    return [
        llm_param.ToolSchema(
            name="Bash",
            type="function",
            description="Run shell commands",
            parameters={
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Command to run"},
                },
                "required": ["command"],
            },
        )
    ]


def test_render_html_document_skeleton(tmp_path: Path) -> None:
    session = _build_session(tmp_path)
    out = render_session_export_html(
        session,
        system_prompt="You are a terminal coding agent.",
        tools=_tools(),
    )

    # Document shell.
    assert out.startswith("<!DOCTYPE html>") or "<!DOCTYPE html>" in out[:200]
    assert "<html" in out
    assert "</html>" in out.rstrip()[-200:]
    # Inline CSS/JS are embedded (the thing the refactor will extract).
    assert "<style>" in out
    assert "</style>" in out
    assert "<script>" in out
    assert "</script>" in out
    # No unreplaced template placeholders remain.
    for placeholder in (
        "__TITLE__",
        "__CSS__",
        "__JS__",
        "__HEADER__",
        "__SIDEBAR_TITLE__",
        "__SYSTEM_PROMPT_SECTION__",
        "__TOOLS_SECTION__",
        "__SIDEBAR_ITEMS__",
        "__ENTRY_ITEMS__",
    ):
        assert placeholder not in out, f"placeholder {placeholder} not substituted"


def test_render_html_includes_title_and_header(tmp_path: Path) -> None:
    session = _build_session(tmp_path)
    out = render_session_export_html(session, system_prompt=None, tools=None)

    assert "Golden Export - klaude session export" in out
    # Header hero + meta-grid markers.
    assert 'class="hero-title"' in out
    assert 'class="meta-grid"' in out
    assert 'class="stats-grid"' in out
    assert "Session ID" in out
    assert "Work Dir" in out


def test_render_html_includes_content_and_sections(tmp_path: Path) -> None:
    session = _build_session(tmp_path)
    out = render_session_export_html(
        session,
        system_prompt="You are a terminal coding agent.",
        tools=_tools(),
    )

    # System prompt + tools sections.
    assert "System Prompt" in out
    assert "You are a terminal coding agent." in out
    assert "Available Tools" in out
    assert "Run shell commands" in out
    # Entry content.
    assert "Implemented the feature." in out
    assert "Checkpoint 1" in out
    assert "call_1" in out
    # Entry kinds present.
    assert 'class="entry-card user"' in out
    assert 'class="entry-card assistant"' in out
    assert 'class="entry-card tool"' in out


def test_render_html_omits_sections_when_no_prompt_or_tools(tmp_path: Path) -> None:
    session = _build_session(tmp_path)
    with_sections = render_session_export_html(session, system_prompt="You are an agent.", tools=_tools())
    without = render_session_export_html(session, system_prompt=None, tools=None)

    # The collapsible section panels are present only when prompt/tools exist.
    # "System Prompt" / "Tools" labels still appear in the header meta-grid,
    # but the <span class="panel-title"> markers are section-only.
    assert '<span class="panel-title">System Prompt</span>' in with_sections
    assert '<span class="panel-title">Available Tools</span>' in with_sections
    assert '<span class="panel-title">System Prompt</span>' not in without
    assert '<span class="panel-title">Available Tools</span>' not in without


def test_render_html_empty_session_shows_empty_state(tmp_path: Path) -> None:
    session = Session.create(work_dir=tmp_path)
    out = render_session_export_html(session, system_prompt=None, tools=None)

    assert "No conversation history yet." in out
    assert "Nothing to export yet. Start a conversation first." in out


# ---------------------------------------------------------------------------
# Pure section renderers
# ---------------------------------------------------------------------------


def test_render_system_prompt_section_empty_returns_empty_string() -> None:
    assert esh._render_system_prompt_section(None) == ""
    assert esh._render_system_prompt_section("") == ""


def test_render_system_prompt_section_reports_line_count() -> None:
    html_out = esh._render_system_prompt_section("line1\nline2\nline3")
    assert "System Prompt" in html_out
    assert "3 lines" in html_out
    assert "<details" in html_out


def test_render_tools_section_empty_returns_empty_string() -> None:
    assert esh._render_tools_section([]) == ""


def test_render_tools_section_counts_registered() -> None:
    html_out = esh._render_tools_section(_tools())
    assert "Available Tools" in html_out
    assert "1 registered" in html_out


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_text_preview_collapses_whitespace() -> None:
    assert esh._text_preview("  a   b\n\nc  ") == "a b c"


def test_text_preview_truncates_with_ellipsis() -> None:
    out = esh._text_preview("x" * 500)
    assert out.endswith("...")
    # Default limit is _PREVIEW_LIMIT; truncation slices to limit-1 then appends "...".
    assert len(out) == esh._PREVIEW_LIMIT - 1 + len("...")


def test_text_preview_fallback_on_empty() -> None:
    assert esh._text_preview("   ", fallback="none") == "none"


def test_format_number_thousands_separator() -> None:
    assert esh._format_number(1234567) == "1,234,567"
    assert esh._format_number(0) == "0"


def test_format_timestamp_value_zero_and_none() -> None:
    assert esh._format_timestamp_value(None) == "unknown"
    assert esh._format_timestamp_value(0) == "unknown"
    assert esh._format_timestamp_value(-5) == "unknown"


def test_format_datetime_pattern() -> None:
    dt = datetime(2026, 5, 29, 13, 45, 7)
    assert esh._format_datetime(dt) == "2026-05-29 13:45:07"


def test_usage_summary_none_returns_none() -> None:
    assert esh._usage_summary(None) is None


def test_usage_summary_disjoint_categories() -> None:
    from klaude_code.protocol.models import Usage

    usage = Usage(
        input_tokens=100,
        output_tokens=40,
        cached_tokens=30,
        cache_write_tokens=10,
        reasoning_tokens=15,
    )
    summary = esh._usage_summary(usage)
    assert summary is not None
    # net_input = 100 - 30 - 10 = 60; net_output = 40 - 15 = 25.
    assert "in 60" in summary
    assert "out 25" in summary
    assert "cached 30" in summary
    assert "cache write 10" in summary
    assert "thinking 15" in summary


def test_pretty_json_text_roundtrips_valid_json() -> None:
    out = esh._pretty_json_text('{"b":1,"a":2}')
    # Keys sorted, indent=2.
    assert out == '{\n  "a": 2,\n  "b": 1\n}'


def test_pretty_json_text_returns_raw_on_invalid() -> None:
    assert esh._pretty_json_text("not json") == "not json"


def test_schema_type_label_variants() -> None:
    assert esh._schema_type_label({"type": "string"}) == "string"
    assert esh._schema_type_label({"type": ["string", "null"]}) == "string | null"
    assert esh._schema_type_label({"enum": ["a", "b"]}) == "enum"
