from __future__ import annotations

import asyncio
import io

from rich.console import Console

from klaude_code.protocol import events, message, model, tools
from klaude_code.tui.commands import (
    FlushOpenBlocks,
    PrintBlankLine,
    RenderDeveloperMessage,
    RenderError,
    RenderToolCall,
    RenderToolResult,
    RenderUserMessage,
)
from klaude_code.tui.components.sub_agent import render_sub_agent_call
from klaude_code.tui.machine import DisplayStateMachine
from klaude_code.tui.renderer import TUICommandRenderer


def _renderer_and_output() -> tuple[TUICommandRenderer, io.StringIO]:
    renderer = TUICommandRenderer()
    output = io.StringIO()
    renderer.console = Console(file=output, theme=renderer.themes.app_theme, width=100, force_terminal=False)
    renderer.console.push_theme(renderer.themes.markdown_theme)
    return renderer, output


def test_turn_start_does_not_add_extra_blank_line_before_retry_error() -> None:
    renderer, output = _renderer_and_output()
    session_id = "main"

    asyncio.run(
        renderer.execute(
            [
                RenderUserMessage(event=events.UserMessageEvent(session_id=session_id, content="retry me")),
                RenderError(
                    event=events.ErrorEvent(session_id=session_id, error_message="Retrying 1/10", can_retry=True)
                ),
            ]
        )
    )

    rendered = output.getvalue()
    assert "✘ Retrying 1/10" in rendered


def test_multiline_error_continuation_uses_single_grid_indent() -> None:
    renderer, output = _renderer_and_output()
    session_id = "main"

    asyncio.run(
        renderer.execute(
            [
                RenderError(
                    event=events.ErrorEvent(
                        session_id=session_id,
                        error_message=(
                            "Prompt cache break detected: likely server-side\n"
                            "Cached tokens: 5,120 -> 0 (drop: 5,120)\n"
                            "Report: /tmp/cache-break.txt"
                        ),
                        can_retry=True,
                    )
                ),
            ]
        )
    )

    rendered = output.getvalue()
    lines = rendered.splitlines()
    assert lines[0].rstrip() == "✘ Prompt cache break detected: likely server-side"
    assert lines[1].rstrip() == "  Cached tokens: 5,120 -> 0 (drop: 5,120)"
    assert lines[2].rstrip() == "  Report: /tmp/cache-break.txt"
    assert not lines[2].startswith("    Report:")


def test_developer_messages_stay_grouped_until_turn_boundary() -> None:
    renderer, output = _renderer_and_output()
    session_id = "main"

    asyncio.run(
        renderer.execute(
            [
                RenderDeveloperMessage(
                    event=events.DeveloperMessageEvent(
                        session_id=session_id,
                        item=message.DeveloperMessage(
                            parts=[],
                            ui_extra=model.DeveloperUIExtra(items=[model.SkillActivatedUIItem(name="commit")]),
                        ),
                    )
                ),
                RenderDeveloperMessage(
                    event=events.DeveloperMessageEvent(
                        session_id=session_id,
                        item=message.DeveloperMessage(
                            parts=[],
                            ui_extra=model.DeveloperUIExtra(items=[model.SkillActivatedUIItem(name="submit-pr")]),
                        ),
                    )
                ),
                PrintBlankLine(),
            ]
        )
    )

    rendered = output.getvalue()
    assert "+ Activated skill commit\n+ Activated skill submit-pr\n\n" in rendered
    assert "+ Activated skill commit\n\n+ Activated skill submit-pr" not in rendered


def test_tool_call_and_result_stay_grouped_until_next_visible_block() -> None:
    renderer, output = _renderer_and_output()
    session_id = "main"

    asyncio.run(
        renderer.execute(
            [
                RenderToolCall(
                    event=events.ToolCallEvent(
                        session_id=session_id,
                        tool_call_id="tool-1",
                        tool_name=tools.BASH,
                        arguments='{"command":"echo hi"}',
                    )
                ),
                RenderToolResult(
                    event=events.ToolResultEvent(
                        session_id=session_id,
                        tool_call_id="tool-1",
                        tool_name=tools.BASH,
                        result="hi",
                        status="success",
                    ),
                    is_sub_agent_session=False,
                ),
                RenderUserMessage(event=events.UserMessageEvent(session_id=session_id, content="next")),
            ]
        )
    )

    rendered = output.getvalue()
    assert "next" in rendered
    assert "\n\n└ hi" not in rendered


def test_turn_start_flushes_open_tool_block_before_spinner_updates() -> None:
    renderer, output = _renderer_and_output()
    machine = DisplayStateMachine()
    session_id = "main"

    asyncio.run(
        renderer.execute(
            [
                RenderToolCall(
                    event=events.ToolCallEvent(
                        session_id=session_id,
                        tool_call_id="tool-1",
                        tool_name=tools.BASH,
                        arguments='{"command":"echo hi"}',
                    )
                )
            ]
        )
    )

    commands = machine.transition(events.TurnStartEvent(session_id=session_id))

    assert any(isinstance(cmd, FlushOpenBlocks) for cmd in commands)

    asyncio.run(renderer.execute(commands))

    assert renderer._tool_block_open is False  # type: ignore[reportPrivateUsage]
    assert output.getvalue().endswith("\n\n")


def test_sub_agent_call_prompt_renders_as_markdown() -> None:
    output = io.StringIO()
    console = Console(file=output, width=100, force_terminal=False)

    console.print(
        render_sub_agent_call(
            model.SubAgentState(
                sub_agent_type="finder",
                sub_agent_desc="searching",
                sub_agent_prompt="## Plan\n\n- item",
            ),
            code_theme="monokai",
        )
    )

    rendered = output.getvalue()
    assert "## Plan" not in rendered
    assert "Plan" in rendered
    assert " • item" in rendered
