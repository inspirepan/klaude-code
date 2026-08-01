from __future__ import annotations

import asyncio
import io
from itertools import pairwise

from rich.console import Console

from klaude_code.protocol import events, message, tools
from klaude_code.protocol.models import DeveloperUIExtra, SkillActivatedUIItem, SubAgentState
from klaude_code.tui.commands import (
    AppendAssistant,
    AppendThinking,
    EndAssistantStream,
    EndThinkingStream,
    PrintBlankLine,
    RenderCompactToolResult,
    RenderDeveloperMessage,
    RenderError,
    RenderNotice,
    RenderSideQuestion,
    RenderSubAgentBatchSummary,
    RenderSubAgentThinking,
    RenderTaskFinish,
    RenderTaskStart,
    RenderToolCall,
    RenderToolResult,
    RenderUserMessage,
    StartAssistantStream,
    StartThinkingStream,
    SubAgentSummary,
)
from klaude_code.tui.components.sub_agent import render_sub_agent_call
from klaude_code.tui.machine import DisplayStateMachine
from klaude_code.tui.renderer import TUICommandRenderer
from klaude_code.tui.transcript_detail import Detail


def _renderer_and_output() -> tuple[TUICommandRenderer, io.StringIO]:
    renderer = TUICommandRenderer()
    output = io.StringIO()
    renderer.console = Console(file=output, theme=renderer.themes.app_theme, width=100, force_terminal=False)
    renderer.console.push_theme(renderer.themes.markdown_theme)
    return renderer, output


def test_step_start_does_not_add_extra_blank_line_before_retry_error() -> None:
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


def test_existing_boundary_is_not_duplicated_before_next_input() -> None:
    renderer, output = _renderer_and_output()
    session_id = "main"

    asyncio.run(
        renderer.execute(
            [
                RenderUserMessage(event=events.UserMessageEvent(session_id=session_id, content="/debug")),
                RenderNotice(event=events.NoticeEvent(session_id=session_id, content="Log file: /tmp/debug.log")),
                PrintBlankLine(),
                RenderUserMessage(event=events.UserMessageEvent(session_id=session_id, content="next")),
            ]
        )
    )

    rendered = output.getvalue()
    lines = [line.rstrip() for line in rendered.splitlines()]
    notice_index = lines.index("Log file: /tmp/debug.log")
    assert lines[notice_index : notice_index + 3] == ["Log file: /tmp/debug.log", "", "❯  next"]


def test_side_question_wraps_long_answer_without_truncating() -> None:
    renderer, output = _renderer_and_output()
    answer = "这是一段需要完整换行显示的长答案。" * 20 + "保留到结尾"

    asyncio.run(
        renderer.execute(
            [
                RenderSideQuestion(
                    event=events.SideQuestionEvent(
                        session_id="main",
                        question="完整内容是什么？",
                        answer=answer,
                        cache_hit_rate=0.99,
                    )
                )
            ]
        )
    )

    rendered = output.getvalue()
    assert "保留到结尾" in rendered
    assert "…" not in rendered


def test_standard_transcript_blocks_have_exactly_one_blank_line_between_them() -> None:
    renderer, output = _renderer_and_output()
    session_id = "main"

    asyncio.run(
        renderer.execute(
            [
                RenderUserMessage(event=events.UserMessageEvent(session_id=session_id, content="user-a")),
                StartAssistantStream(session_id=session_id),
                AppendAssistant(session_id=session_id, content="assistant-a"),
                EndAssistantStream(session_id=session_id),
                RenderNotice(event=events.NoticeEvent(session_id=session_id, content="notice-a")),
                RenderUserMessage(event=events.UserMessageEvent(session_id=session_id, content="user-b")),
            ]
        )
    )

    lines = [line.rstrip() for line in output.getvalue().splitlines()]
    block_indexes = [
        next(index for index, line in enumerate(lines) if marker in line)
        for marker in ("user-a", "assistant-a", "notice-a", "user-b")
    ]
    for left, right in pairwise(block_indexes):
        assert lines[left + 1 : right] == [""]


def test_compact_thinking_between_tools_keeps_block_contiguous() -> None:
    """Compact mode previews reasoning in the prompt live area, not scrollback.
    Thinking between two tool calls must not break the contiguous tool block
    with a blank line."""

    renderer, output = _renderer_and_output()
    session_id = "main"

    def _bash(tool_call_id: str, command: str) -> RenderCompactToolResult:
        return RenderCompactToolResult(
            event=events.ToolResultEvent(
                session_id=session_id,
                tool_call_id=tool_call_id,
                tool_name=tools.BASH,
                result="ok",
                status="success",
            ),
            arguments=f'{{"command":"{command}"}}',
        )

    asyncio.run(
        renderer.execute(
            [
                _bash("bash-1", "ls"),
                StartThinkingStream(session_id=session_id),
                AppendThinking(session_id=session_id, content="deciding the next command"),
                EndThinkingStream(session_id=session_id),
                _bash("bash-2", "pwd"),
            ]
        )
    )
    renderer.flush_open_blocks()

    lines = [line.rstrip() for line in output.getvalue().splitlines()]
    first = next(index for index, line in enumerate(lines) if "ls" in line)
    second = next(index for index, line in enumerate(lines) if "pwd" in line)
    assert second == first + 1


def test_developer_and_tool_group_is_continuous_until_next_standard_block() -> None:
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
                            ui_extra=DeveloperUIExtra(items=[SkillActivatedUIItem(name="commit")]),
                        ),
                    )
                ),
                RenderToolCall(
                    event=events.ToolCallEvent(
                        session_id=session_id,
                        tool_call_id="bash-1",
                        tool_name=tools.BASH,
                        arguments='{"command":"echo hi"}',
                    )
                ),
                RenderToolResult(
                    event=events.ToolResultEvent(
                        session_id=session_id,
                        tool_call_id="bash-1",
                        tool_name=tools.BASH,
                        result="hi",
                        status="success",
                    ),
                    is_sub_agent_session=False,
                ),
                RenderDeveloperMessage(
                    event=events.DeveloperMessageEvent(
                        session_id=session_id,
                        item=message.DeveloperMessage(
                            parts=[],
                            ui_extra=DeveloperUIExtra(items=[SkillActivatedUIItem(name="submit-pr")]),
                        ),
                    )
                ),
                RenderNotice(event=events.NoticeEvent(session_id=session_id, content="done")),
            ]
        )
    )

    lines = [line.rstrip() for line in output.getvalue().splitlines()]
    first_developer = next(index for index, line in enumerate(lines) if "commit" in line)
    second_developer = next(index for index, line in enumerate(lines) if "submit-pr" in line)
    notice = lines.index("done")
    assert "" not in lines[first_developer : second_developer + 1]
    assert lines[second_developer + 1 : notice] == [""]


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


def test_developer_messages_stay_grouped_until_step_boundary() -> None:
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
                            ui_extra=DeveloperUIExtra(items=[SkillActivatedUIItem(name="commit")]),
                        ),
                    )
                ),
                RenderDeveloperMessage(
                    event=events.DeveloperMessageEvent(
                        session_id=session_id,
                        item=message.DeveloperMessage(
                            parts=[],
                            ui_extra=DeveloperUIExtra(items=[SkillActivatedUIItem(name="submit-pr")]),
                        ),
                    )
                ),
                PrintBlankLine(),
            ]
        )
    )

    rendered = output.getvalue()
    assert "  + Activated skill commit\n  + Activated skill submit-pr\n\n" in rendered
    assert "+ Activated skill commit\n\n+ Activated skill submit-pr" not in rendered


def test_hidden_todo_call_transitions_developer_block_to_tool_block() -> None:
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
                            ui_extra=DeveloperUIExtra(items=[SkillActivatedUIItem(name="commit")]),
                        ),
                    )
                ),
                RenderToolCall(
                    event=events.ToolCallEvent(
                        session_id=session_id,
                        tool_call_id="todo-1",
                        tool_name=tools.TODO_WRITE,
                        arguments='{"todos":[]}',
                    )
                ),
                RenderToolResult(
                    event=events.ToolResultEvent(
                        session_id=session_id,
                        tool_call_id="todo-1",
                        tool_name=tools.TODO_WRITE,
                        result="Updated todos",
                        status="success",
                    ),
                    is_sub_agent_session=False,
                ),
                StartAssistantStream(session_id=session_id),
                AppendAssistant(session_id=session_id, content="done"),
                EndAssistantStream(session_id=session_id),
            ]
        )
    )

    lines = output.getvalue().splitlines()
    panel_end = next(index for index, line in enumerate(lines) if "╰" in line)
    assert lines[panel_end : panel_end + 3] == ["    ╰────────────────╯", "", "● done"]


def test_todo_result_stays_grouped_with_following_tool() -> None:
    renderer, output = _renderer_and_output()
    session_id = "main"

    asyncio.run(
        renderer.execute(
            [
                RenderToolCall(
                    event=events.ToolCallEvent(
                        session_id=session_id,
                        tool_call_id="todo-1",
                        tool_name=tools.TODO_WRITE,
                        arguments='{"todos":[]}',
                    )
                ),
                RenderToolResult(
                    event=events.ToolResultEvent(
                        session_id=session_id,
                        tool_call_id="todo-1",
                        tool_name=tools.TODO_WRITE,
                        result="Updated todos",
                        status="success",
                    ),
                    is_sub_agent_session=False,
                ),
                RenderToolCall(
                    event=events.ToolCallEvent(
                        session_id=session_id,
                        tool_call_id="bash-1",
                        tool_name=tools.BASH,
                        arguments='{"command":"uv run pytest"}',
                    )
                ),
            ]
        )
    )
    renderer.flush_open_blocks()

    lines = output.getvalue().splitlines()
    panel_end = next(index for index, line in enumerate(lines) if "╰" in line)
    assert lines[panel_end + 1].startswith("  $ Bash")


def test_sub_agent_blank_line_keeps_quote_prefix() -> None:
    renderer, output = _renderer_and_output()
    session_id = "sub-1"
    renderer.register_session(
        session_id,
        SubAgentState(sub_agent_type="finder", sub_agent_desc="searching", sub_agent_prompt="prompt"),
    )

    asyncio.run(renderer.execute([PrintBlankLine(session_id=session_id)]))

    assert output.getvalue() == "▌ \n"


def test_sub_agent_finish_result_does_not_include_trailing_quote_blank_line() -> None:
    renderer, output = _renderer_and_output()
    renderer.set_transcript_detail(Detail.FULL)
    session_id = "sub-1"

    asyncio.run(
        renderer.execute(
            [
                RenderTaskStart(
                    event=events.TaskStartEvent(
                        session_id=session_id,
                        model_id="test-model",
                        sub_agent_state=SubAgentState(
                            sub_agent_type="finder",
                            sub_agent_desc="searching",
                            sub_agent_prompt="prompt",
                        ),
                    )
                ),
                RenderTaskFinish(event=events.TaskFinishEvent(session_id=session_id, task_result="done")),
            ]
        )
    )

    assert output.getvalue().endswith("▌  searching \n▌ done\n")


def test_sub_agent_finish_blank_line_after_result_is_not_quoted() -> None:
    renderer, output = _renderer_and_output()
    renderer.set_transcript_detail(Detail.FULL)
    machine = DisplayStateMachine()
    machine.set_transcript_detail(Detail.FULL)
    main_session = "main"
    sub_session = "sub-1"

    commands = [
        *machine.transition(events.TaskStartEvent(session_id=main_session, model_id="test-model")),
        *machine.transition(
            events.TaskStartEvent(
                session_id=sub_session,
                model_id="test-model",
                sub_agent_state=SubAgentState(
                    sub_agent_type="finder",
                    sub_agent_desc="searching",
                    sub_agent_prompt="prompt",
                ),
            )
        ),
        *machine.transition(events.TaskFinishEvent(session_id=sub_session, task_result="done")),
    ]

    asyncio.run(renderer.execute(commands))

    assert output.getvalue().endswith("▌  searching \n▌ done\n\n")
    assert not output.getvalue().endswith("▌  searching \n▌ done\n▌ \n")


def test_sub_agent_developer_and_tool_blocks_have_no_blank_lines_between_them() -> None:
    renderer, output = _renderer_and_output()
    renderer.set_transcript_detail(Detail.FULL)
    session_id = "sub-1"
    renderer.register_session(
        session_id,
        SubAgentState(sub_agent_type="finder", sub_agent_desc="searching", sub_agent_prompt="prompt"),
    )

    asyncio.run(
        renderer.execute(
            [
                RenderDeveloperMessage(
                    event=events.DeveloperMessageEvent(
                        session_id=session_id,
                        item=message.DeveloperMessage(
                            parts=[], ui_extra=DeveloperUIExtra(items=[SkillActivatedUIItem(name="commit")])
                        ),
                    )
                ),
                RenderToolCall(
                    event=events.ToolCallEvent(
                        session_id=session_id,
                        tool_call_id="tool-1",
                        tool_name=tools.READ,
                        arguments='{"file_path":"gpt-image-gen/SKILL.md","limit":1}',
                    )
                ),
                RenderDeveloperMessage(
                    event=events.DeveloperMessageEvent(
                        session_id=session_id,
                        item=message.DeveloperMessage(
                            parts=[], ui_extra=DeveloperUIExtra(items=[SkillActivatedUIItem(name="submit-pr")])
                        ),
                    )
                ),
            ]
        )
    )

    rendered = output.getvalue()
    assert "▌   + Activated skill commit\n▌   → Read" in rendered
    assert "▌   → Read Skill" in rendered
    assert "SKILL.md 1:1\n▌   + Activated skill submit-pr" in rendered
    assert "commit\n▌ \n▌ → Read" not in rendered
    assert "SKILL.md 1:1\n▌ \n▌ + Activated skill submit-pr" not in rendered


def test_sub_agent_block_flush_can_force_top_level_blank_line() -> None:
    renderer, output = _renderer_and_output()
    renderer.set_transcript_detail(Detail.FULL)
    session_id = "sub-1"
    renderer.register_session(
        session_id,
        SubAgentState(sub_agent_type="finder", sub_agent_desc="searching", sub_agent_prompt="prompt"),
    )

    asyncio.run(
        renderer.execute(
            [
                RenderDeveloperMessage(
                    event=events.DeveloperMessageEvent(
                        session_id=session_id,
                        item=message.DeveloperMessage(
                            parts=[], ui_extra=DeveloperUIExtra(items=[SkillActivatedUIItem(name="commit")])
                        ),
                    )
                )
            ]
        )
    )
    renderer.flush_open_blocks(scoped=False)

    assert output.getvalue().endswith("▌   + Activated skill commit\n\n")
    assert not output.getvalue().endswith("▌ + Activated skill commit\n▌ \n")


def test_sub_agent_tool_group_flush_keeps_quote_prefix() -> None:
    renderer, output = _renderer_and_output()
    renderer.set_transcript_detail(Detail.FULL)
    session_id = "sub-1"
    renderer.register_session(
        session_id,
        SubAgentState(sub_agent_type="finder", sub_agent_desc="searching", sub_agent_prompt="prompt"),
    )

    asyncio.run(
        renderer.execute(
            [
                RenderToolResult(
                    event=events.ToolResultEvent(
                        session_id=session_id,
                        tool_call_id="tool-1",
                        tool_name=tools.BASH,
                        result="done",
                        status="success",
                    ),
                    is_sub_agent_session=True,
                ),
            ]
        )
    )
    renderer.flush_open_blocks()

    assert output.getvalue().endswith("▌             done\n▌ \n")


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


def test_stream_end_emits_single_blank_line_in_interactive_mode() -> None:
    renderer, output = _renderer_and_output()
    session_id = "main"
    # Thinking only reaches the transcript in expanded mode; compact previews it
    # below the prompt instead.
    renderer.set_transcript_detail(Detail.FULL)

    asyncio.run(
        renderer.execute(
            [
                StartAssistantStream(session_id=session_id),
                AppendAssistant(session_id=session_id, content="hello"),
                EndAssistantStream(session_id=session_id),
                StartThinkingStream(session_id=session_id),
                AppendThinking(session_id=session_id, content="thinking"),
                EndThinkingStream(session_id=session_id),
            ]
        )
    )

    rendered = output.getvalue()
    assert "● hello\n\n∵ thinking" in rendered
    assert "● hello\n\n\n∵ thinking" not in rendered


def test_sub_agent_thinking_content_uses_scoped_quote() -> None:
    renderer, output = _renderer_and_output()
    session_id = "sub-1"
    renderer.register_session(
        session_id,
        SubAgentState(sub_agent_type="finder", sub_agent_desc="searching", sub_agent_prompt="prompt"),
    )

    asyncio.run(
        renderer.execute(
            [
                RenderSubAgentThinking(
                    session_id=session_id,
                    content="Full reasoning\n\n- first detail\n- second detail",
                ),
            ]
        )
    )

    rendered = output.getvalue()
    assert "▌ Full reasoning" in rendered
    assert "▌  • first detail" in rendered
    assert "▌  • second detail" in rendered
    assert "Thought for" not in rendered


def test_compact_sub_agent_summary_shows_model_and_success_ellipsis() -> None:
    renderer, output = _renderer_and_output()
    renderer.register_session(
        "sub-success",
        SubAgentState(sub_agent_type="finder", sub_agent_desc="search", sub_agent_prompt="prompt"),
    )
    renderer.register_session(
        "sub-error",
        SubAgentState(sub_agent_type="finder", sub_agent_desc="fail", sub_agent_prompt="prompt"),
    )

    asyncio.run(
        renderer.execute(
            [
                RenderSubAgentBatchSummary(
                    summaries=(
                        SubAgentSummary(
                            session_id="sub-success",
                            title="Finder",
                            description="search",
                            status="success",
                            model_id="gpt-5.6-luna",
                            duration_s=12.0,
                            tool_count=3,
                            token_count=1200,
                            result_summary="Found the path.",
                        ),
                        SubAgentSummary(
                            session_id="sub-error",
                            title="Finder",
                            description="fail",
                            status="error",
                            model_id="gpt-5.6-luna",
                            duration_s=4.0,
                            tool_count=1,
                            token_count=None,
                            result_summary="Child failed",
                        ),
                    )
                )
            ]
        )
    )

    rendered = output.getvalue()
    assert "gpt-5.6-luna · 12s · 3 tools · 1.2K tokens" in rendered
    assert "▌ ↳ Found the path." in rendered
    assert "Child failed…" not in rendered


def test_compact_sub_agent_summary_before_list_has_one_blank_line() -> None:
    renderer, output = _renderer_and_output()
    renderer.register_session(
        "sub-success",
        SubAgentState(sub_agent_type="finder", sub_agent_desc="search", sub_agent_prompt="prompt"),
    )

    asyncio.run(
        renderer.execute(
            [
                RenderSubAgentBatchSummary(
                    summaries=(
                        SubAgentSummary(
                            session_id="sub-success",
                            title="Finder",
                            description="search",
                            status="success",
                            model_id="gpt-5.6-luna",
                            duration_s=1.0,
                            tool_count=1,
                            token_count=100,
                            result_summary="Found it.",
                        ),
                    )
                ),
                StartAssistantStream(session_id="main"),
                AppendAssistant(session_id="main", content="- first\n- second"),
                EndAssistantStream(session_id="main"),
            ]
        )
    )

    lines = output.getvalue().splitlines()
    summary_index = next(index for index, line in enumerate(lines) if "Found it." in line)
    assistant_index = next(index for index, line in enumerate(lines) if "first" in line)
    assert lines[summary_index + 1 : assistant_index] == [""]


def test_replay_stream_end_emits_single_blank_line_before_tool_call() -> None:
    renderer, output = _renderer_and_output()
    renderer.set_replay_mode(True)
    session_id = "main"

    asyncio.run(
        renderer.execute(
            [
                StartAssistantStream(session_id=session_id),
                AppendAssistant(session_id=session_id, content="hello"),
                EndAssistantStream(session_id=session_id),
                RenderToolCall(
                    event=events.ToolCallEvent(
                        session_id=session_id,
                        tool_call_id="tool-1",
                        tool_name=tools.APPLY_PATCH,
                        arguments="{}",
                    )
                ),
            ]
        )
    )

    rendered = output.getvalue()
    assert "● hello\n\n  ± Patch" in rendered
    assert "● hello\n\n\n± Patch" not in rendered


def test_step_start_keeps_consecutive_tool_steps_grouped_until_assistant_message() -> None:
    renderer, output = _renderer_and_output()
    renderer.set_transcript_detail(Detail.FULL)
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
                        arguments='{"command":"one"}',
                    )
                )
            ]
        )
    )

    commands = machine.transition(events.StepStartEvent(session_id=session_id))
    asyncio.run(renderer.execute(commands))

    asyncio.run(
        renderer.execute(
            [
                RenderToolCall(
                    event=events.ToolCallEvent(
                        session_id=session_id,
                        tool_call_id="tool-2",
                        tool_name=tools.BASH,
                        arguments='{"command":"two"}',
                    )
                ),
                StartAssistantStream(session_id=session_id),
                AppendAssistant(session_id=session_id, content="done"),
                EndAssistantStream(session_id=session_id),
            ]
        )
    )

    assert "  $ Bash    one\n  $ Bash    two\n\n● done\n\n" in output.getvalue()


def test_replay_step_start_keeps_consecutive_tool_steps_grouped() -> None:
    renderer, output = _renderer_and_output()
    renderer.set_transcript_detail(Detail.FULL)
    machine = DisplayStateMachine()
    session_id = "main"

    commands = [
        RenderToolCall(
            event=events.ToolCallEvent(
                session_id=session_id,
                tool_call_id="tool-1",
                tool_name=tools.BASH,
                arguments='{"command":"one"}',
            )
        ),
        RenderToolResult(
            event=events.ToolResultEvent(
                session_id=session_id,
                tool_call_id="tool-1",
                tool_name=tools.BASH,
                result="one",
                status="success",
                is_last_in_step=True,
            ),
            is_sub_agent_session=False,
        ),
        *machine.transition_rebuild(events.StepStartEvent(session_id=session_id)),
        RenderToolCall(
            event=events.ToolCallEvent(
                session_id=session_id,
                tool_call_id="tool-2",
                tool_name=tools.BASH,
                arguments='{"command":"two"}',
            )
        ),
    ]

    asyncio.run(renderer.execute(commands))

    assert "    one\n  $ Bash    two" in output.getvalue()


def test_sub_agent_call_prompt_renders_as_markdown() -> None:
    renderer, output = _renderer_and_output()

    renderer.console.print(
        render_sub_agent_call(
            SubAgentState(
                sub_agent_type="finder",
                sub_agent_desc="searching",
                sub_agent_prompt="## Plan\n\n- item",
            ),
            code_theme="monokai",
            effective_model="gpt-5.4-mini",
        )
    )

    rendered = output.getvalue()
    assert "## Plan" not in rendered
    assert "Plan" in rendered
    assert " • item" in rendered
    assert "[model default: gpt-5.4-mini]" in rendered


def test_sub_agent_call_identifies_model_override() -> None:
    renderer, output = _renderer_and_output()

    renderer.console.print(
        render_sub_agent_call(
            SubAgentState(
                sub_agent_type="finder",
                sub_agent_desc="searching",
                sub_agent_prompt="Find it",
                model="sonnet",
            ),
            effective_model="claude-sonnet-4-6",
        )
    )

    rendered = output.getvalue()
    assert "[model override: sonnet]" in rendered
    assert "model default" not in rendered
