from __future__ import annotations

import os
from collections.abc import Sequence

import pytest
from rich.text import Text

from klaude_code.protocol import events, tools
from klaude_code.protocol.models import (
    BashUIExtra,
    SessionIdUIExtra,
    SubAgentState,
    TaskMetadata,
    TaskMetadataItem,
    TodoItem,
    TodoListUIExtra,
    TodoUIExtra,
    Usage,
)
from klaude_code.tui import machine as machine_module
from klaude_code.tui.commands import (
    AppendBashCommandOutput,
    DynamicSeparatorText,
    PrintBlankLine,
    RenderBashCommandEnd,
    RenderCommand,
    RenderCompactToolResult,
    RenderSubAgentBatchSummary,
    RenderTaskFinish,
    RenderThinkingSummary,
    RenderToolResult,
    SpinnerStatusLine,
    SpinnerUpdate,
)
from klaude_code.tui.components.rich.status import DynamicText
from klaude_code.tui.machine import DisplayStateMachine


def _last_spinner_update(cmds: Sequence[RenderCommand]) -> SpinnerUpdate:
    for cmd in reversed(cmds):
        if isinstance(cmd, SpinnerUpdate):
            return cmd
    raise AssertionError("SpinnerUpdate not found")


def _line_plain(line: object) -> str:
    if isinstance(line, SpinnerStatusLine):
        return _line_plain(line.text)
    if isinstance(line, Text):
        return line.plain
    plain = getattr(line, "plain", None)
    if isinstance(plain, str):
        return plain
    return str(line)


def _right_plain(update: SpinnerUpdate) -> str:
    right = update.right_text
    if right is None:
        return ""
    render = getattr(right, "render", None)
    if callable(render):
        rendered = render(compact=False)
        if isinstance(rendered, Text):
            return rendered.plain
    plain = getattr(right, "plain", None)
    if isinstance(plain, str):
        return plain
    return str(right)


def test_sub_agent_status_lines_hide_main_reasoning() -> None:
    machine = DisplayStateMachine()
    main_session = "main"
    sub_session = "sub-1"

    machine.transition(events.TaskStartEvent(session_id=main_session, model_id="test-model"))
    machine.transition(events.ThinkingStartEvent(session_id=main_session))

    cmds = machine.transition(
        events.TaskStartEvent(
            session_id=sub_session,
            sub_agent_state=SubAgentState(
                sub_agent_type="finder",
                sub_agent_desc="searching xxxxx",
                sub_agent_prompt="prompt",
            ),
            model_id="test-model",
        )
    )
    update = _last_spinner_update(cmds)

    assert update.leading_blank_line is True
    assert update.status_lines[0].session_id == sub_session
    lines = [_line_plain(line) for line in update.status_lines]
    assert lines == [
        "Finder: searching xxxxx · test-model · Running… · 0s",
        "Initializing…",
    ]
    first_line = update.status_lines[0].text
    if isinstance(first_line, DynamicText):
        first_line = first_line.snapshot()
    assert isinstance(first_line, Text)
    assert any(
        span.style == "italic" and first_line.plain[span.start : span.end] == "searching xxxxx"
        for span in first_line.spans
    )


def test_sub_agent_status_line_shows_tool_counts() -> None:
    machine = DisplayStateMachine()
    main_session = "main"
    sub_session = "sub-1"

    machine.transition(events.TaskStartEvent(session_id=main_session, model_id="test-model"))
    machine.transition(
        events.TaskStartEvent(
            session_id=sub_session,
            sub_agent_state=SubAgentState(
                sub_agent_type="finder",
                sub_agent_desc="searching yyyyy",
                sub_agent_prompt="prompt",
            ),
            model_id="test-model",
        )
    )

    cmds = machine.transition(
        events.ToolCallStartEvent(
            session_id=sub_session,
            tool_call_id="tc1",
            tool_name=tools.BASH,
        )
    )
    update = _last_spinner_update(cmds)
    lines = [_line_plain(line) for line in update.status_lines]
    assert lines == [
        "Finder: searching yyyyy · test-model · Running… · 0s",
        "Bash",
    ]

    cmds = machine.transition(
        events.ToolCallStartEvent(
            session_id=sub_session,
            tool_call_id="tc2",
            tool_name=tools.BASH,
        )
    )
    update = _last_spinner_update(cmds)
    lines = [_line_plain(line) for line in update.status_lines]
    assert lines == [
        "Finder: searching yyyyy · test-model · Running… · 0s",
        "Bash",
    ]


def test_sub_agent_latest_tool_defers_long_target_truncation_to_renderer() -> None:
    machine = DisplayStateMachine()
    machine.transition(events.TaskStartEvent(session_id="main", model_id="test-model"))
    machine.transition(
        events.TaskStartEvent(
            session_id="sub-1",
            sub_agent_state=SubAgentState(
                sub_agent_type="finder",
                sub_agent_desc="reading history",
                sub_agent_prompt="prompt",
            ),
            model_id="test-model",
        )
    )
    long_path = "outside/" + "nested/" * 8 + "history.py"

    machine.transition(
        events.ToolCallEvent(
            session_id="sub-1",
            tool_call_id="read-long",
            tool_name=tools.READ,
            arguments=f'{{"file_path":"{long_path}"}}',
        )
    )
    commands = machine.transition(events.ThinkingStartEvent(session_id="sub-1"))

    assert _line_plain(_last_spinner_update(commands).status_lines[1]) == f"Read {long_path}"


def test_sub_agent_status_line_shows_completed_tool_count_before_activity() -> None:
    machine = DisplayStateMachine()
    machine.transition(events.TaskStartEvent(session_id="main", model_id="test-model"))
    machine.transition(
        events.TaskStartEvent(
            session_id="sub-1",
            parent_session_id="main",
            sub_agent_state=SubAgentState(
                sub_agent_type="finder",
                sub_agent_desc="tracking usage stats",
                sub_agent_prompt="prompt",
            ),
            model_id="test-model",
        )
    )
    for index in range(2):
        call_id = f"read-{index}"
        machine.transition(
            events.ToolCallEvent(
                session_id="sub-1",
                tool_call_id=call_id,
                tool_name=tools.READ,
                arguments='{"file_path":"stats.py"}',
            )
        )
        machine.transition(
            events.ToolResultEvent(
                session_id="sub-1",
                tool_call_id=call_id,
                tool_name=tools.READ,
                result="content",
                status="success",
            )
        )

    machine.transition(events.ThinkingStartEvent(session_id="sub-1"))
    thinking = machine.transition(events.ThinkingDeltaEvent(session_id="sub-1", content="reviewing"))
    assert [_line_plain(line) for line in _last_spinner_update(thinking).status_lines] == [
        "Finder: tracking usage stats · test-model · 2 tools · Thinking… · 0s",
        "Read stats.py ✓",
    ]

    machine.transition(events.ThinkingEndEvent(session_id="sub-1"))
    machine.transition(events.AssistantTextStartEvent(session_id="sub-1"))
    commands = machine.transition(events.AssistantTextDeltaEvent(session_id="sub-1", content="result"))

    assert [_line_plain(line) for line in _last_spinner_update(commands).status_lines] == [
        "Finder: tracking usage stats · test-model · 2 tools · Typing… · 0s",
        "Read stats.py ✓",
    ]


def test_sub_agent_status_tracks_thinking_and_typing_char_counts(monkeypatch: pytest.MonkeyPatch) -> None:
    now = 102.0
    monkeypatch.setattr(machine_module.time, "time", lambda: now)
    machine = DisplayStateMachine()
    main_session = "main"
    sub_session = "sub-1"

    machine.transition(events.TaskStartEvent(session_id=main_session, model_id="test-model"))
    machine.transition(
        events.TaskStartEvent(
            session_id=sub_session,
            sub_agent_state=SubAgentState(
                sub_agent_type="general-purpose",
                sub_agent_desc="compressing context",
                sub_agent_prompt="prompt",
            ),
            model_id="test-model",
            timestamp=100.0,
        )
    )

    first_step = machine.transition(events.StepStartEvent(session_id=sub_session))
    assert [_line_plain(line) for line in _last_spinner_update(first_step).status_lines] == [
        "GeneralPurpose: compressing context · test-model · Running… · 2s",
        "Initializing…",
    ]

    machine.transition(events.ThinkingStartEvent(session_id=sub_session, timestamp=100.0))
    machine.transition(events.ThinkingDeltaEvent(session_id=sub_session, content="x" * 1234, timestamp=101.0))
    thinking = machine.transition(events.ThinkingDeltaEvent(session_id=sub_session, content=" second", timestamp=102.0))
    assert [_line_plain(line) for line in _last_spinner_update(thinking).status_lines] == [
        "GeneralPurpose: compressing context · test-model · Thinking… · 2s",
        "Initializing…",
    ]

    now = 125.0
    assert [_line_plain(line) for line in _last_spinner_update(thinking).status_lines] == [
        "GeneralPurpose: compressing context · test-model · Thinking… · 25s",
        "Initializing…",
    ]

    ended = machine.transition(events.ThinkingEndEvent(session_id=sub_session, timestamp=120.0))
    assert not any(isinstance(cmd, RenderThinkingSummary) for cmd in ended)
    assert [_line_plain(line) for line in _last_spinner_update(ended).status_lines] == [
        "GeneralPurpose: compressing context · test-model · Running… · 25s",
        "Initializing…",
    ]

    machine.transition(events.AssistantTextStartEvent(session_id=sub_session))
    typing = machine.transition(events.AssistantTextDeltaEvent(session_id=sub_session, content="y" * 2345))
    assert [_line_plain(line) for line in _last_spinner_update(typing).status_lines] == [
        "GeneralPurpose: compressing context · test-model · Typing… · 25s",
        "Initializing…",
    ]

    composed = machine.transition(events.AssistantTextEndEvent(session_id=sub_session))
    assert [_line_plain(line) for line in _last_spinner_update(composed).status_lines] == [
        "GeneralPurpose: compressing context · test-model · Running… · 25s",
        "Initializing…",
    ]

    second_step = machine.transition(events.StepStartEvent(session_id=sub_session))
    assert [_line_plain(line) for line in _last_spinner_update(second_step).status_lines] == [
        "GeneralPurpose: compressing context · test-model · Running… · 25s",
        "Initializing…",
    ]


def test_sub_agent_new_step_clears_interrupted_thinking() -> None:
    machine = DisplayStateMachine()
    sub_session = "sub-1"
    machine.transition(events.TaskStartEvent(session_id="main", model_id="test-model"))
    machine.transition(
        events.TaskStartEvent(
            session_id=sub_session,
            sub_agent_state=SubAgentState(
                sub_agent_type="finder",
                sub_agent_desc="retrying",
                sub_agent_prompt="prompt",
            ),
            model_id="test-model",
        )
    )
    machine.transition(events.ThinkingStartEvent(session_id=sub_session))
    machine.transition(events.ThinkingDeltaEvent(session_id=sub_session, content="stale thinking"))

    machine.transition(events.StepStartEvent(session_id=sub_session))
    machine.transition(events.AssistantTextStartEvent(session_id=sub_session))
    typing = machine.transition(events.AssistantTextDeltaEvent(session_id=sub_session, content="answer"))

    assert [_line_plain(line) for line in _last_spinner_update(typing).status_lines] == [
        "Finder: retrying · test-model · Typing… · 0s",
        "Initializing…",
    ]


def test_main_agent_replay_summary_omits_unrecoverable_duration() -> None:
    machine = DisplayStateMachine()
    main_session = "main"
    machine.transition_replay(events.TaskStartEvent(session_id=main_session, model_id="test-model"))
    machine.transition_replay(events.ThinkingStartEvent(session_id=main_session, timestamp=100.0))
    machine.transition_replay(events.ThinkingDeltaEvent(session_id=main_session, content="你好，世界", timestamp=100.0))

    ended = machine.transition_replay(events.ThinkingEndEvent(session_id=main_session, timestamp=100.0))

    summary = next(cmd for cmd in ended if isinstance(cmd, RenderThinkingSummary))
    assert summary.duration_s is None
    assert summary.char_count == 5


def test_main_agent_compact_thinking_uses_persisted_duration() -> None:
    machine = DisplayStateMachine()
    session_id = "main"
    machine.transition(events.TaskStartEvent(session_id=session_id, model_id="test-model", timestamp=100.0))
    machine.transition(events.ThinkingStartEvent(session_id=session_id, timestamp=101.0))
    machine.transition(events.ThinkingDeltaEvent(session_id=session_id, content="reasoning", timestamp=102.0))

    commands = machine.transition(events.ThinkingEndEvent(session_id=session_id, timestamp=103.0, duration_s=1.5))

    summary = next(command for command in commands if isinstance(command, RenderThinkingSummary))
    assert summary.duration_s == 1.5
    assert summary.char_count == 9
    assert summary.content == "reasoning"


def test_sub_agent_batch_stays_fixed_until_all_children_finish(monkeypatch: pytest.MonkeyPatch) -> None:
    now = 105.0
    monkeypatch.setattr(machine_module.time, "time", lambda: now)
    machine = DisplayStateMachine()
    machine.transition(events.TaskStartEvent(session_id="main", model_id="test-model", timestamp=100.0))
    for index, session_id in enumerate(("sub-a", "sub-b")):
        machine.transition(
            events.TaskStartEvent(
                session_id=session_id,
                parent_session_id="main",
                sub_agent_state=SubAgentState(
                    sub_agent_type="finder",
                    sub_agent_desc=f"task {index}",
                    sub_agent_prompt="prompt",
                    parent_tool_batch_id="response-1",
                    parent_tool_batch_index=index,
                    parent_tool_batch_size=2,
                ),
                model_id="test-model",
                timestamp=100.0 + index,
            )
        )

    machine.transition(
        events.ToolCallEvent(
            session_id="sub-a",
            response_id="child-response",
            tool_call_id="read-1",
            tool_name=tools.READ,
            arguments='{"file_path":"src/a.py","offset":10,"limit":5}',
        )
    )
    machine.transition(
        events.ToolResultEvent(
            session_id="sub-a",
            response_id="child-response",
            tool_call_id="read-1",
            tool_name=tools.READ,
            result="contents",
            status="success",
        )
    )
    machine.transition(
        events.TaskMetadataEvent(
            session_id="sub-a",
            metadata=TaskMetadataItem(main_agent=TaskMetadata(usage=Usage(input_tokens=100, output_tokens=20))),
        )
    )
    first_finished = machine.transition(
        events.TaskFinishEvent(
            session_id="sub-a",
            task_result="## Result\n\n- Found the replay path.\n\nAlso checked the renderer tests.",
            timestamp=105.0,
        )
    )

    assert not any(isinstance(command, RenderSubAgentBatchSummary) for command in first_finished)
    first_status = _last_spinner_update(first_finished)
    assert [_line_plain(line) for line in first_status.status_lines] == [
        "Finder: task 0 · test-model · 1 tool ✓ · 5s",
        "Result Found the replay path. Also checked the renderer tests.",
        "Finder: task 1 · test-model · Running… · 4s",
        "Initializing…",
    ]

    now = 108.0
    second_finished = machine.transition(
        events.TaskFinishEvent(session_id="sub-b", task_result="Second result.", timestamp=108.0)
    )
    batch = next(command for command in second_finished if isinstance(command, RenderSubAgentBatchSummary))
    assert [summary.session_id for summary in batch.summaries] == ["sub-a", "sub-b"]
    assert batch.summaries[0].result_summary == "Result Found the replay path. Also checked the renderer tests."
    assert batch.summaries[0].model_id == "test-model"
    assert batch.summaries[0].tool_count == 1
    assert batch.summaries[0].token_count == 120
    assert _last_spinner_update(second_finished).reset_bottom_height is True


def test_sub_agent_batch_closes_when_sibling_never_spawns() -> None:
    machine = DisplayStateMachine()
    machine.transition(events.TaskStartEvent(session_id="main", model_id="test-model"))
    machine.transition(
        events.TaskStartEvent(
            session_id="sub-a",
            parent_session_id="main",
            sub_agent_state=SubAgentState(
                sub_agent_type="finder",
                sub_agent_desc="valid child",
                sub_agent_prompt="prompt",
                parent_tool_batch_id="response-1",
                parent_tool_batch_index=0,
                parent_tool_batch_size=2,
            ),
            model_id="test-model",
        )
    )
    first_finished = machine.transition(events.TaskFinishEvent(session_id="sub-a", task_result="done"))
    assert not any(isinstance(command, RenderSubAgentBatchSummary) for command in first_finished)

    failed_sibling = machine.transition(
        events.ToolResultEvent(
            session_id="main",
            response_id="response-1",
            tool_call_id="agent-b",
            tool_name=tools.AGENT,
            result="Unknown Agent type",
            status="error",
        )
    )

    batch = next(command for command in failed_sibling if isinstance(command, RenderSubAgentBatchSummary))
    assert [summary.session_id for summary in batch.summaries] == ["sub-a"]


def test_expanded_mode_keeps_full_thinking_stream_commands() -> None:
    machine = DisplayStateMachine()
    machine.set_compact_transcript(False)
    machine.transition(events.TaskStartEvent(session_id="main", model_id="test-model"))

    started = machine.transition(events.ThinkingStartEvent(session_id="main"))
    delta = machine.transition(events.ThinkingDeltaEvent(session_id="main", content="full thought"))
    ended = machine.transition(events.ThinkingEndEvent(session_id="main", duration_s=1.0))

    from klaude_code.tui.commands import AppendThinking, EndThinkingStream, StartThinkingStream

    assert any(isinstance(command, StartThinkingStream) for command in started)
    assert any(isinstance(command, AppendThinking) for command in delta)
    assert any(isinstance(command, EndThinkingStream) for command in ended)
    assert not any(isinstance(command, RenderThinkingSummary) for command in ended)


def test_main_session_bash_tool_streams_append_only_and_keeps_success_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(machine_module, "BASH_STREAM_DELAY_SEC", 0.0)
    machine = DisplayStateMachine()
    session_id = "main"

    machine.transition(events.TaskStartEvent(session_id=session_id, model_id="test-model"))

    stream_cmds = machine.transition(
        events.ToolOutputDeltaEvent(
            session_id=session_id,
            tool_call_id="bash-1",
            tool_name=tools.BASH,
            content="hello\n",
        )
    )
    assert any(isinstance(cmd, AppendBashCommandOutput) for cmd in stream_cmds)
    assert not any(isinstance(cmd, RenderToolResult) for cmd in stream_cmds)

    result_cmds = machine.transition(
        events.ToolResultEvent(
            session_id=session_id,
            tool_call_id="bash-1",
            tool_name=tools.BASH,
            result="hello",
            status="success",
        )
    )
    assert any(isinstance(cmd, RenderBashCommandEnd) for cmd in result_cmds)
    assert any(isinstance(cmd, RenderCompactToolResult) for cmd in result_cmds)
    assert not any(isinstance(cmd, RenderToolResult) for cmd in result_cmds)


def test_main_session_bash_tool_buffers_before_delay_and_falls_back_to_tool_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(machine_module, "BASH_STREAM_DELAY_SEC", 3.0)
    machine = DisplayStateMachine()
    session_id = "main"

    machine.transition(events.TaskStartEvent(session_id=session_id, model_id="test-model"))
    machine.transition(
        events.ToolCallEvent(
            session_id=session_id,
            tool_call_id="bash-1",
            tool_name=tools.BASH,
            arguments="{}",
            timestamp=100.0,
        )
    )

    stream_cmds = machine.transition(
        events.ToolOutputDeltaEvent(
            session_id=session_id,
            tool_call_id="bash-1",
            tool_name=tools.BASH,
            content="hello\n",
            timestamp=101.0,
        )
    )
    assert stream_cmds == []

    result_cmds = machine.transition(
        events.ToolResultEvent(
            session_id=session_id,
            tool_call_id="bash-1",
            tool_name=tools.BASH,
            result="hello",
            status="success",
            timestamp=102.0,
        )
    )
    assert not any(isinstance(cmd, AppendBashCommandOutput) for cmd in result_cmds)
    assert not any(isinstance(cmd, RenderBashCommandEnd) for cmd in result_cmds)
    assert any(isinstance(cmd, RenderCompactToolResult) for cmd in result_cmds)
    assert not any(isinstance(cmd, RenderToolResult) for cmd in result_cmds)


def test_sub_agent_todo_write_result_is_rendered() -> None:
    machine = DisplayStateMachine()
    main_session = "main"
    sub_session = "sub-1"

    machine.transition(events.TaskStartEvent(session_id=main_session, model_id="test-model"))
    machine.transition(
        events.TaskStartEvent(
            session_id=sub_session,
            sub_agent_state=SubAgentState(
                sub_agent_type="finder",
                sub_agent_desc="tracking progress",
                sub_agent_prompt="prompt",
            ),
            model_id="test-model",
        )
    )

    cmds = machine.transition(
        events.ToolResultEvent(
            session_id=sub_session,
            tool_call_id="todo-1",
            tool_name=tools.TODO_WRITE,
            result="Todos updated",
            status="success",
            ui_extra=TodoListUIExtra(
                todo_list=TodoUIExtra(
                    todos=[TodoItem(content="Review matches", status="in_progress")],
                    new_completed=[],
                )
            ),
        )
    )

    tool_results = [cmd for cmd in cmds if isinstance(cmd, RenderToolResult)]
    assert len(tool_results) == 1
    assert tool_results[0].event.tool_name == tools.TODO_WRITE
    assert tool_results[0].is_sub_agent_session is True


def test_main_session_bash_tool_flushes_buffer_after_delay(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(machine_module, "BASH_STREAM_DELAY_SEC", 3.0)
    machine = DisplayStateMachine()
    session_id = "main"

    machine.transition(events.TaskStartEvent(session_id=session_id, model_id="test-model"))
    machine.transition(
        events.ToolCallEvent(
            session_id=session_id,
            tool_call_id="bash-1",
            tool_name=tools.BASH,
            arguments="{}",
            timestamp=100.0,
        )
    )

    machine.transition(
        events.ToolOutputDeltaEvent(
            session_id=session_id,
            tool_call_id="bash-1",
            tool_name=tools.BASH,
            content="hello\n",
            timestamp=101.0,
        )
    )
    stream_cmds = machine.transition(
        events.ToolOutputDeltaEvent(
            session_id=session_id,
            tool_call_id="bash-1",
            tool_name=tools.BASH,
            content="world\n",
            timestamp=103.5,
        )
    )
    bash_chunks = [cmd.event.content for cmd in stream_cmds if isinstance(cmd, AppendBashCommandOutput)]
    assert bash_chunks == ["hello\n", "world\n"]


def test_bash_mode_end_emits_final_tool_result_from_streamed_output() -> None:
    machine = DisplayStateMachine()
    session_id = "main"

    machine.transition(events.TaskStartEvent(session_id=session_id, model_id="test-model"))
    machine.transition(events.BashCommandStartEvent(session_id=session_id, command="echo hi"))
    machine.transition(events.BashCommandOutputDeltaEvent(session_id=session_id, content="hello\n"))

    end_cmds = machine.transition(events.BashCommandEndEvent(session_id=session_id, exit_code=0, cancelled=False))

    assert any(isinstance(cmd, RenderBashCommandEnd) for cmd in end_cmds)
    tool_results = [cmd for cmd in end_cmds if isinstance(cmd, RenderToolResult)]
    assert len(tool_results) == 1
    assert tool_results[0].event.tool_name == tools.BASH
    assert tool_results[0].event.result == "hello"
    assert tool_results[0].event.status == "success"
    assert not any(isinstance(cmd, PrintBlankLine) for cmd in end_cmds)


def test_bash_mode_end_includes_nonzero_exit_message_in_final_tool_result() -> None:
    machine = DisplayStateMachine()
    session_id = "main"

    machine.transition(events.TaskStartEvent(session_id=session_id, model_id="test-model"))
    machine.transition(events.BashCommandStartEvent(session_id=session_id, command="false"))

    end_cmds = machine.transition(events.BashCommandEndEvent(session_id=session_id, exit_code=2, cancelled=False))

    tool_results = [cmd for cmd in end_cmds if isinstance(cmd, RenderToolResult)]
    assert len(tool_results) == 1
    assert tool_results[0].event.result == "Command exited with code 2"
    assert tool_results[0].event.status == "success"


def test_sub_agent_bash_tool_output_delta_is_ignored() -> None:
    machine = DisplayStateMachine()
    main_session = "main"
    sub_session = "sub-1"

    machine.transition(events.TaskStartEvent(session_id=main_session, model_id="test-model"))
    machine.transition(
        events.TaskStartEvent(
            session_id=sub_session,
            sub_agent_state=SubAgentState(
                sub_agent_type="finder",
                sub_agent_desc="searching yyyyy",
                sub_agent_prompt="prompt",
            ),
            model_id="test-model",
        )
    )

    cmds = machine.transition(
        events.ToolOutputDeltaEvent(
            session_id=sub_session,
            tool_call_id="bash-sub-1",
            tool_name=tools.BASH,
            content="hello\n",
        )
    )

    assert cmds == []


def test_sub_agent_status_lines_cap_with_more_indicator(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(machine_module.shutil, "get_terminal_size", lambda fallback: os.terminal_size((120, 10)))
    machine = DisplayStateMachine()
    main_session = "main"
    machine.transition(events.TaskStartEvent(session_id=main_session, model_id="test-model"))

    last_update: SpinnerUpdate | None = None
    for idx in range(7):
        cmds = machine.transition(
            events.TaskStartEvent(
                session_id=f"sub-{idx}",
                sub_agent_state=SubAgentState(
                    sub_agent_type="finder",
                    sub_agent_desc=f"searching {idx}",
                    sub_agent_prompt="prompt",
                ),
                model_id="test-model",
            )
        )
        last_update = _last_spinner_update(cmds)

    assert last_update is not None
    lines = [_line_plain(line) for line in last_update.status_lines]
    assert lines == [
        "Finder: searching 0 · test-model · Running… · 0s",
        "Initializing…",
        "… 6 more agents",
    ]

    monkeypatch.setattr(machine_module.shutil, "get_terminal_size", lambda fallback: os.terminal_size((120, 6)))
    short_terminal = machine.transition(events.ThinkingStartEvent(session_id="sub-0"))
    assert [_line_plain(line) for line in _last_spinner_update(short_terminal).status_lines] == [
        "Finder: searching 0 · test-model · Thinking… · 0s",
        "Initializing…",
    ]


def test_sub_agent_finish_triggers_bottom_height_reset() -> None:
    machine = DisplayStateMachine()
    main_session = "main"
    sub_session = "sub-1"

    machine.transition(events.TaskStartEvent(session_id=main_session, model_id="test-model"))
    start_cmds = machine.transition(
        events.TaskStartEvent(
            session_id=sub_session,
            sub_agent_state=SubAgentState(
                sub_agent_type="finder",
                sub_agent_desc="searching",
                sub_agent_prompt="prompt",
            ),
            model_id="test-model",
        )
    )
    start_update = _last_spinner_update(start_cmds)
    assert start_update.reset_bottom_height is False

    finish_cmds = machine.transition(
        events.TaskFinishEvent(
            session_id=sub_session,
            task_result="done",
        )
    )
    finish_update = _last_spinner_update(finish_cmds)
    assert finish_update.reset_bottom_height is True
    assert finish_update.leading_blank_line is False


def test_sub_agent_finish_emits_unscoped_blank_line_after_result() -> None:
    machine = DisplayStateMachine()
    machine.set_compact_transcript(False)
    main_session = "main"
    sub_session = "sub-1"

    machine.transition(events.TaskStartEvent(session_id=main_session, model_id="test-model"))
    machine.transition(
        events.TaskStartEvent(
            session_id=sub_session,
            sub_agent_state=SubAgentState(
                sub_agent_type="finder",
                sub_agent_desc="searching",
                sub_agent_prompt="prompt",
            ),
            model_id="test-model",
        )
    )

    finish_cmds = machine.transition(
        events.TaskFinishEvent(
            session_id=sub_session,
            task_result="done",
        )
    )

    render_task_finish_index = next(i for i, cmd in enumerate(finish_cmds) if isinstance(cmd, RenderTaskFinish))
    print_blank_line = next(cmd for cmd in finish_cmds if isinstance(cmd, PrintBlankLine))
    print_blank_line_index = finish_cmds.index(print_blank_line)

    assert print_blank_line_index > render_task_finish_index
    assert print_blank_line.session_id is None


def test_nested_sub_agent_finish_emits_parent_scoped_blank_line() -> None:
    machine = DisplayStateMachine()
    machine.set_compact_transcript(False)
    main_session = "main"
    parent_session = "sub-parent"
    child_session = "sub-child"

    machine.transition(events.TaskStartEvent(session_id=main_session, model_id="test-model"))
    machine.transition(
        events.TaskStartEvent(
            session_id=parent_session,
            parent_session_id=main_session,
            sub_agent_state=SubAgentState(
                sub_agent_type="general-purpose",
                sub_agent_desc="parent",
                sub_agent_prompt="prompt",
            ),
            model_id="test-model",
        )
    )
    machine.transition(
        events.TaskStartEvent(
            session_id=child_session,
            parent_session_id=parent_session,
            sub_agent_state=SubAgentState(
                sub_agent_type="finder",
                sub_agent_desc="child",
                sub_agent_prompt="prompt",
            ),
            model_id="test-model",
        )
    )

    finish_cmds = machine.transition(events.TaskFinishEvent(session_id=child_session, task_result="done"))
    print_blank_line = next(cmd for cmd in finish_cmds if isinstance(cmd, PrintBlankLine))

    assert print_blank_line.session_id == parent_session


def test_main_agent_tool_call_shows_spawning_task_before_sub_agent_starts() -> None:
    machine = DisplayStateMachine()
    main_session = "main"

    machine.transition(events.TaskStartEvent(session_id=main_session, model_id="test-model"))
    cmds = machine.transition(
        events.ToolCallStartEvent(
            session_id=main_session,
            tool_call_id="tc-task-1",
            tool_name=tools.AGENT,
        )
    )
    update = _last_spinner_update(cmds)
    assert update.leading_blank_line is False
    assert len(update.status_lines) == 1
    assert _line_plain(update.status_lines[0]).startswith("Running Task")


def test_main_bash_tool_call_adds_blank_line_before_stream_starts() -> None:
    machine = DisplayStateMachine()
    main_session = "main"

    machine.transition(events.TaskStartEvent(session_id=main_session, model_id="test-model"))
    cmds = machine.transition(
        events.ToolCallStartEvent(
            session_id=main_session,
            tool_call_id="tc-bash-1",
            tool_name=tools.BASH,
        )
    )

    update = _last_spinner_update(cmds)
    assert update.leading_blank_line is False
    assert update.top_blank_line is True
    assert len(update.status_lines) == 1
    assert _line_plain(update.status_lines[0]).startswith("Bashing")


def test_main_bash_compact_status_prefers_clamped_description() -> None:
    machine = DisplayStateMachine()
    main_session = "main"
    description = "x" * 50

    machine.transition(events.TaskStartEvent(session_id=main_session, model_id="test-model"))
    machine.transition(
        events.ToolCallStartEvent(
            session_id=main_session,
            tool_call_id="tc-bash-1",
            tool_name=tools.BASH,
        )
    )
    commands = machine.transition(
        events.ToolCallEvent(
            session_id=main_session,
            tool_call_id="tc-bash-1",
            tool_name=tools.BASH,
            arguments=f'{{"command":"echo hi","description":"{description}"}}',
        )
    )

    update = _last_spinner_update(commands)
    assert _line_plain(update.status_lines[0]) == f"Bash {'x' * 39}…"

    result_commands = machine.transition(
        events.ToolResultEvent(
            session_id=main_session,
            tool_call_id="tc-bash-1",
            tool_name=tools.BASH,
            result="done",
            status="success",
            ui_extra=BashUIExtra(exit_code=0),
        )
    )
    compact = next(command for command in result_commands if isinstance(command, RenderCompactToolResult))
    assert compact.arguments == f'{{"command":"echo hi","description":"{description}"}}'
    assert not any(isinstance(command, RenderToolResult) for command in result_commands)


def test_main_session_composing_keeps_sub_agent_activity_priority() -> None:
    machine = DisplayStateMachine()
    main_session = "main"

    machine.transition(events.TaskStartEvent(session_id=main_session, model_id="test-model"))
    machine.transition(
        events.ToolCallStartEvent(
            session_id=main_session,
            tool_call_id="tc-task-1",
            tool_name=tools.AGENT,
        )
    )

    cmds = machine.transition(events.AssistantTextStartEvent(session_id=main_session, response_id="r1"))
    update = _last_spinner_update(cmds)

    assert len(update.status_lines) == 1
    assert _line_plain(update.status_lines[0]).startswith("Running Task")
    assert "Typing" not in _line_plain(update.status_lines[0])


def test_interrupt_clears_stale_sub_agent_status_lines() -> None:
    machine = DisplayStateMachine()
    main_session = "main"
    sub_session = "sub-1"

    machine.transition(events.TaskStartEvent(session_id=main_session, model_id="test-model"))
    machine.transition(
        events.TaskStartEvent(
            session_id=sub_session,
            sub_agent_state=SubAgentState(
                sub_agent_type="finder",
                sub_agent_desc="searching",
                sub_agent_prompt="prompt",
            ),
            model_id="test-model",
        )
    )

    machine.transition(events.InterruptEvent(session_id=main_session))

    restart_cmds = machine.transition(events.TaskStartEvent(session_id=main_session, model_id="test-model"))
    update = _last_spinner_update(restart_cmds)

    assert update.leading_blank_line is False
    assert len(update.status_lines) == 1
    assert update.status_lines[0].session_id is None
    assert "Finder" not in _line_plain(update.status_lines[0])


def test_sub_agent_non_retry_error_clears_status_lines() -> None:
    machine = DisplayStateMachine()
    main_session = "main"
    sub_session = "sub-1"

    machine.transition(events.TaskStartEvent(session_id=main_session, model_id="test-model"))
    machine.transition(
        events.TaskStartEvent(
            session_id=sub_session,
            sub_agent_state=SubAgentState(
                sub_agent_type="finder",
                sub_agent_desc="searching",
                sub_agent_prompt="prompt",
            ),
            model_id="test-model",
        )
    )

    cmds = machine.transition(
        events.ErrorEvent(
            session_id=sub_session,
            error_message="sub-agent failed",
            can_retry=False,
        )
    )
    update = _last_spinner_update(cmds)

    assert update.reset_bottom_height is True
    assert update.leading_blank_line is False
    assert len(update.status_lines) == 1
    assert update.status_lines[0].session_id is None
    assert "Finder" not in _line_plain(update.status_lines[0])


def test_failed_agent_tool_result_clears_sub_agent_status_line() -> None:
    machine = DisplayStateMachine()
    main_session = "main"
    sub_session = "sub-1"

    machine.transition(events.TaskStartEvent(session_id=main_session, model_id="test-model"))
    machine.transition(
        events.TaskStartEvent(
            session_id=sub_session,
            sub_agent_state=SubAgentState(
                sub_agent_type="finder",
                sub_agent_desc="searching",
                sub_agent_prompt="prompt",
            ),
            model_id="test-model",
        )
    )
    machine.transition(
        events.ToolCallStartEvent(
            session_id=main_session,
            tool_call_id="tc-agent-1",
            tool_name=tools.AGENT,
        )
    )

    cmds = machine.transition(
        events.ToolResultEvent(
            session_id=main_session,
            tool_call_id="tc-agent-1",
            tool_name=tools.AGENT,
            result="Failed to run sub-agent",
            status="error",
            ui_extra=SessionIdUIExtra(session_id=sub_session),
        )
    )
    update = _last_spinner_update(cmds)

    assert update.reset_bottom_height is True
    assert update.leading_blank_line is False
    assert len(update.status_lines) == 1
    assert update.status_lines[0].session_id is None
    assert "Finder" not in _line_plain(update.status_lines[0])


def test_main_session_tokens_accumulate_across_task_boundaries() -> None:
    machine = DisplayStateMachine()
    session_id = "main"

    machine.transition(events.TaskStartEvent(session_id=session_id, model_id="test-model"))
    usage_cmds = machine.transition(
        events.UsageEvent(
            session_id=session_id,
            usage=Usage(
                input_tokens=30_000,
                cached_tokens=20_000,
                output_tokens=12_000,
                reasoning_tokens=2_000,
                input_cost=0.001,
                output_cost=0.002,
                cache_read_cost=0.0005,
            ),
        )
    )
    first_update = _last_spinner_update(usage_cmds)
    assert first_update.right_text is not None
    assert "in 10k · cache 20k · out 10k · thought 2k" in _right_plain(first_update)
    assert "cost $0.0035" in _right_plain(first_update)

    machine.transition(
        events.TaskFinishEvent(
            session_id=session_id,
            task_result="done",
        )
    )

    restart_cmds = machine.transition(events.TaskStartEvent(session_id=session_id, model_id="test-model"))
    restart_update = _last_spinner_update(restart_cmds)
    assert restart_update.right_text is not None
    assert "in 10k · cache 20k · out 10k · thought 2k" in _right_plain(restart_update)
    assert "cost $0.0035" in _right_plain(restart_update)

    usage_cmds = machine.transition(
        events.UsageEvent(
            session_id=session_id,
            usage=Usage(
                input_tokens=11_000,
                cached_tokens=1_000,
                output_tokens=7_000,
                reasoning_tokens=2_000,
                input_cost=0.0003,
                output_cost=0.0007,
                cache_read_cost=0.0001,
            ),
        )
    )
    second_update = _last_spinner_update(usage_cmds)
    assert second_update.right_text is not None
    assert "in 20k · cache 21k · out 15k · thought 4k" in _right_plain(second_update)
    assert "cost $0.0046" in _right_plain(second_update)


def test_spinner_update_separates_elapsed_interrupt_hint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(machine_module, "current_elapsed_text", lambda: "1m51s")

    machine = DisplayStateMachine()
    session_id = "main"
    machine.transition(events.TaskStartEvent(session_id=session_id, model_id="test-model"))
    cmds = machine.transition(
        events.UsageEvent(
            session_id=session_id,
            usage=Usage(
                input_tokens=30_000,
                cached_tokens=20_000,
                output_tokens=12_000,
                reasoning_tokens=2_000,
                input_cost=0.001,
                output_cost=0.002,
                cache_read_cost=0.0005,
            ),
        )
    )

    update = _last_spinner_update(cmds)
    metadata = _right_plain(update)

    assert "in 10k · cache 20k · out 10k · thought 2k" in metadata
    assert "1m51s" not in metadata
    assert "esc to interrupt" not in metadata
    assert isinstance(update.separator_text, DynamicSeparatorText)
    assert update.separator_text.render() == "1m51s · esc to interrupt"
