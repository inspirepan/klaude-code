from __future__ import annotations

import asyncio
import io

from rich.console import Console

from klaude_code.protocol import events, message, model, tools
from klaude_code.tui.commands import (
    RenderDeveloperMessage,
    RenderError,
    RenderToolCall,
    RenderToolResult,
    RenderTurnStart,
    RenderUserMessage,
)
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
                RenderTurnStart(event=events.TurnStartEvent(session_id=session_id)),
                RenderError(
                    event=events.ErrorEvent(session_id=session_id, error_message="Retrying 1/10", can_retry=True)
                ),
            ]
        )
    )

    rendered = output.getvalue()
    assert "❯ retry me\n\n✘ Retrying 1/10\n\n" in rendered
    assert "❯ retry me\n\n\n✘ Retrying 1/10" not in rendered


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
                RenderTurnStart(event=events.TurnStartEvent(session_id=session_id)),
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
    assert "\n\n❯ next\n\n" in rendered
    assert "\n\n└ hi" not in rendered
