"""Characterization tests for ``DisplayStateMachine._transition``.

These lock in the CURRENT sequence of ``RenderCommand`` objects produced for
representative protocol event sequences. They exist to protect a future split
of the ~670-line ``_transition`` method: any refactor must keep the emitted
command lists byte-for-byte identical (modulo command identity / field values
asserted here).

We do NOT assert what the behavior *should* be -- only what it currently IS.
"""

from __future__ import annotations

from klaude_code.protocol import events
from klaude_code.protocol.llm_param import LLMClientProtocol, LLMConfigParameter
from klaude_code.protocol.models import SubAgentState
from klaude_code.tui import commands as c
from klaude_code.tui.machine import DisplayStateMachine


def _types(cmds: list[c.RenderCommand]) -> list[str]:
    return [type(cmd).__name__ for cmd in cmds]


def _llm_config() -> LLMConfigParameter:
    return LLMConfigParameter(
        protocol=LLMClientProtocol.OPENAI,
        provider_name="demo",
        model_id="gpt-demo",
    )


def _welcome(session_id: str, title: str | None) -> events.WelcomeEvent:
    return events.WelcomeEvent(
        session_id=session_id,
        work_dir="/tmp/project",
        llm_config=_llm_config(),
        title=title,
    )


# ---------------------------------------------------------------------------
# Welcome
# ---------------------------------------------------------------------------


def test_welcome_emits_render_welcome_then_terminal_title() -> None:
    m = DisplayStateMachine()
    cmds = m.transition(_welcome("s1", "Demo"))

    assert _types(cmds) == ["RenderWelcome", "UpdateTerminalTitlePrefix"]
    assert isinstance(cmds[0], c.RenderWelcome)
    assert cmds[0].event.session_id == "s1"
    title_cmd = cmds[1]
    assert isinstance(title_cmd, c.UpdateTerminalTitlePrefix)
    assert title_cmd.session_title == "Demo"
    # WelcomeEvent records the primary session.
    assert m.session_title == "Demo"


def test_welcome_with_new_session_id_resets_then_renders() -> None:
    m = DisplayStateMachine()
    _ = m.transition(_welcome("s1", "First"))
    cmds = m.transition(_welcome("s2", "Second"))

    assert _types(cmds) == ["RenderWelcome", "UpdateTerminalTitlePrefix"]
    assert m.session_title == "Second"


# ---------------------------------------------------------------------------
# User messages + rule-line insertion
# ---------------------------------------------------------------------------


def test_first_user_message_has_no_rule_line() -> None:
    m = DisplayStateMachine()
    cmds = m.transition(events.UserMessageEvent(session_id="s1", content="hello"))

    assert _types(cmds) == ["RenderUserMessage"]


def test_second_user_message_prepends_rule_and_blank() -> None:
    m = DisplayStateMachine()
    _ = m.transition(events.UserMessageEvent(session_id="s1", content="first"))
    cmds = m.transition(events.UserMessageEvent(session_id="s1", content="second"))

    assert _types(cmds) == ["PrintRuleLine", "PrintBlankLine", "RenderUserMessage"]


def test_user_message_rule_skipped_after_interrupt() -> None:
    m = DisplayStateMachine()
    _ = m.transition(events.UserMessageEvent(session_id="s1", content="first"))
    # InterruptEvent sets _skip_next_user_message_rule for the next user message.
    _ = m.transition(events.InterruptEvent(session_id="s1"))
    cmds = m.transition(events.UserMessageEvent(session_id="s1", content="second"))

    assert _types(cmds) == ["RenderUserMessage"]


# ---------------------------------------------------------------------------
# Task lifecycle (live / non-replay)
# ---------------------------------------------------------------------------


def test_task_start_primary_live_command_sequence() -> None:
    m = DisplayStateMachine()
    cmds = m.transition(events.TaskStartEvent(session_id="s1", model_id="test-model"))

    assert _types(cmds) == [
        "TaskClockStart",
        "StartTitleBlink",
        "SpinnerStart",
        "RenderTaskStart",
        "SpinnerUpdate",
    ]
    assert m.terminal_title_prefix == "⠋"  # spinner braille frame


def test_task_start_replay_omits_clock_spinner_title() -> None:
    m = DisplayStateMachine()
    cmds = m.transition_replay(events.TaskStartEvent(session_id="s1", model_id="test-model"))

    assert _types(cmds) == ["RenderTaskStart"]


def test_task_finish_primary_live_full_sequence() -> None:
    m = DisplayStateMachine()
    _ = m.transition(events.TaskStartEvent(session_id="s1", model_id="test-model"))
    cmds = m.transition(events.TaskFinishEvent(session_id="s1", task_result="done"))

    # task_result is non-empty and no assistant deltas were streamed, so the
    # fallback assistant render kicks in before the teardown commands.
    assert _types(cmds) == [
        "RenderTaskFinish",
        "StartAssistantStream",
        "AppendAssistant",
        "EndAssistantStream",
        "TaskClockClear",
        "SpinnerStop",
        "StopTitleBlink",
        "UpdateTerminalTitlePrefix",
    ]
    assert m.terminal_title_prefix == "✅"  # check mark


def test_task_finish_cancelled_result_no_fallback_render() -> None:
    m = DisplayStateMachine()
    _ = m.transition(events.TaskStartEvent(session_id="s1", model_id="test-model"))
    cmds = m.transition(events.TaskFinishEvent(session_id="s1", task_result="Task cancelled"))

    # Cancelled result => no fallback assistant render and no check-mark prefix.
    assert _types(cmds) == [
        "RenderTaskFinish",
        "TaskClockClear",
        "SpinnerStop",
        "StopTitleBlink",
        "UpdateTerminalTitlePrefix",
    ]
    assert m.terminal_title_prefix is None


# ---------------------------------------------------------------------------
# Thinking stream
# ---------------------------------------------------------------------------


def test_thinking_stream_sequence_primary() -> None:
    m = DisplayStateMachine()
    _ = m.transition(events.TaskStartEvent(session_id="s1", model_id="test-model"))

    start = m.transition(events.ThinkingStartEvent(session_id="s1", response_id="r1"))
    delta = m.transition(events.ThinkingDeltaEvent(session_id="s1", response_id="r1", content="reasoning"))
    end = m.transition(events.ThinkingEndEvent(session_id="s1", response_id="r1"))

    assert _types(start) == ["StartThinkingStream", "SpinnerUpdate"]
    assert _types(delta) == ["AppendThinking"]
    assert isinstance(delta[0], c.AppendThinking)
    assert delta[0].content == "reasoning"
    assert _types(end) == ["EndThinkingStream", "SpinnerStart", "SpinnerUpdate"]


def test_thinking_events_dropped_for_non_primary_session() -> None:
    m = DisplayStateMachine()
    _ = m.transition(events.TaskStartEvent(session_id="s1", model_id="test-model"))
    # Different (non-primary, non-sub-agent) session id -> dropped.
    assert m.transition(events.ThinkingStartEvent(session_id="other", response_id="r1")) == []
    assert m.transition(events.ThinkingDeltaEvent(session_id="other", response_id="r1", content="x")) == []


# ---------------------------------------------------------------------------
# Assistant stream
# ---------------------------------------------------------------------------


def test_assistant_stream_sequence_primary() -> None:
    m = DisplayStateMachine()
    _ = m.transition(events.TaskStartEvent(session_id="s1", model_id="test-model"))

    start = m.transition(events.AssistantTextStartEvent(session_id="s1", response_id="r1"))
    delta = m.transition(events.AssistantTextDeltaEvent(session_id="s1", response_id="r1", content="Hi"))
    end = m.transition(events.AssistantTextEndEvent(session_id="s1", response_id="r1"))

    assert _types(start) == ["StartAssistantStream", "SpinnerUpdate"]
    assert _types(delta) == ["AppendAssistant", "SpinnerUpdate"]
    assert isinstance(delta[0], c.AppendAssistant)
    assert delta[0].content == "Hi"
    assert _types(end) == ["EndAssistantStream", "SpinnerStart", "SpinnerUpdate"]


# ---------------------------------------------------------------------------
# Step boundaries
# ---------------------------------------------------------------------------


def test_step_start_flushes_open_blocks_then_spinner_update() -> None:
    m = DisplayStateMachine()
    _ = m.transition(events.TaskStartEvent(session_id="s1", model_id="test-model"))
    cmds = m.transition(events.StepStartEvent(session_id="s1"))

    assert _types(cmds) == ["FlushOpenBlocks", "SpinnerUpdate"]
    assert isinstance(cmds[0], c.FlushOpenBlocks)


def test_step_end_emits_nothing() -> None:
    m = DisplayStateMachine()
    _ = m.transition(events.TaskStartEvent(session_id="s1", model_id="test-model"))
    assert m.transition(events.StepEndEvent(session_id="s1")) == []


# ---------------------------------------------------------------------------
# Notice-family events (all collapse to RenderNotice with formatted content)
# ---------------------------------------------------------------------------


def test_notice_event_passthrough() -> None:
    m = DisplayStateMachine()
    cmds = m.transition(events.NoticeEvent(session_id="s1", content="hi"))
    assert _types(cmds) == ["RenderNotice"]
    assert isinstance(cmds[0], c.RenderNotice)
    assert cmds[0].event.content == "hi"


def test_model_changed_renders_notice_with_default_note() -> None:
    m = DisplayStateMachine()
    cmds = m.transition(events.ModelChangedEvent(session_id="s1", model_id="gpt-x", saved_as_default=True))
    assert _types(cmds) == ["RenderNotice"]
    assert isinstance(cmds[0], c.RenderNotice)
    assert cmds[0].event.content == "Switched to: gpt-x (saved as default)"


def test_thinking_changed_renders_notice() -> None:
    m = DisplayStateMachine()
    cmds = m.transition(events.ThinkingChangedEvent(session_id="s1", previous="off", current="high"))
    assert isinstance(cmds[0], c.RenderNotice)
    assert cmds[0].event.content == "Thinking changed: off -> high"


def test_operation_rejected_formats_busy_notice() -> None:
    m = DisplayStateMachine()
    cmds = m.transition(
        events.OperationRejectedEvent(
            session_id="s1",
            operation_id="op-1",
            operation_type="run_agent",
            reason="session_busy",
            active_task_id="t-9",
        )
    )
    assert _types(cmds) == ["RenderNotice"]
    notice = cmds[0]
    assert isinstance(notice, c.RenderNotice)
    assert notice.event.is_error is True
    assert "operation=run_agent" in notice.event.content
    assert "active_task_id=t-9" in notice.event.content


# ---------------------------------------------------------------------------
# Developer / away / stats / rewind passthroughs
# ---------------------------------------------------------------------------


def test_away_summary_passthrough() -> None:
    m = DisplayStateMachine()
    cmds = m.transition(events.AwaySummaryEvent(session_id="s1", text="recap"))
    assert _types(cmds) == ["RenderAwaySummary"]
    assert isinstance(cmds[0], c.RenderAwaySummary)
    assert cmds[0].event.text == "recap"


def test_developer_message_passthrough() -> None:
    from klaude_code.protocol import message

    m = DisplayStateMachine()
    dev = message.DeveloperMessage(parts=message.text_parts_from_str("<system-reminder>hi</system-reminder>"))
    cmds = m.transition(events.DeveloperMessageEvent(session_id="s1", item=dev))
    assert _types(cmds) == ["RenderDeveloperMessage"]


def test_rewind_event_maps_fields() -> None:
    m = DisplayStateMachine()
    cmds = m.transition(
        events.RewindEvent(
            session_id="s1",
            checkpoint_id=3,
            note="note text",
            rationale="why",
            original_user_message="orig",
            messages_discarded=5,
        )
    )
    assert _types(cmds) == ["RenderRewind"]
    rw = cmds[0]
    assert isinstance(rw, c.RenderRewind)
    assert rw.checkpoint_id == 3
    assert rw.note == "note text"
    assert rw.messages_discarded == 5


# ---------------------------------------------------------------------------
# Interrupt
# ---------------------------------------------------------------------------


def test_interrupt_live_full_sequence() -> None:
    m = DisplayStateMachine()
    _ = m.transition(events.TaskStartEvent(session_id="s1", model_id="test-model"))
    cmds = m.transition(events.InterruptEvent(session_id="s1"))

    assert _types(cmds) == [
        "SpinnerStop",
        "EndThinkingStream",
        "EndAssistantStream",
        "TaskClockClear",
        "StopTitleBlink",
        "UpdateTerminalTitlePrefix",
        "RenderInterrupt",
    ]
    assert m.terminal_title_prefix is None


def test_interrupt_replay_minimal_sequence() -> None:
    m = DisplayStateMachine()
    cmds = m.transition_replay(events.InterruptEvent(session_id="s1"))
    assert _types(cmds) == ["EndThinkingStream", "EndAssistantStream", "RenderInterrupt"]


def test_interrupt_no_notice_omits_render_interrupt() -> None:
    m = DisplayStateMachine()
    _ = m.transition(events.TaskStartEvent(session_id="s1", model_id="test-model"))
    cmds = m.transition(events.InterruptEvent(session_id="s1", show_notice=False))
    assert "RenderInterrupt" not in _types(cmds)


# ---------------------------------------------------------------------------
# Error
# ---------------------------------------------------------------------------


def test_error_non_retryable_tears_down_task() -> None:
    m = DisplayStateMachine()
    _ = m.transition(events.TaskStartEvent(session_id="s1", model_id="test-model"))
    cmds = m.transition(events.ErrorEvent(session_id="s1", error_message="boom", can_retry=False))

    assert _types(cmds) == [
        "RenderError",
        "SpinnerStop",
        "TaskClockClear",
        "StopTitleBlink",
        "UpdateTerminalTitlePrefix",
        "SpinnerUpdate",
    ]
    assert m.terminal_title_prefix == "❌"  # cross mark


def test_error_retryable_keeps_task_running() -> None:
    m = DisplayStateMachine()
    _ = m.transition(events.TaskStartEvent(session_id="s1", model_id="test-model"))
    cmds = m.transition(events.ErrorEvent(session_id="s1", error_message="transient", can_retry=True))

    assert _types(cmds) == ["RenderError", "SpinnerUpdate"]
    # Prefix was set to the spinner frame at task start and is left untouched.
    assert m.terminal_title_prefix == "⠋"


# ---------------------------------------------------------------------------
# End
# ---------------------------------------------------------------------------


def test_end_event_live_resets_everything() -> None:
    m = DisplayStateMachine()
    _ = m.transition(events.TaskStartEvent(session_id="s1", model_id="test-model"))
    cmds = m.transition(events.EndEvent(session_id="s1"))

    assert _types(cmds) == [
        "SpinnerStop",
        "TaskClockClear",
        "StopTitleBlink",
        "UpdateTerminalTitlePrefix",
    ]
    assert m.terminal_title_prefix is None


def test_end_event_replay_emits_nothing() -> None:
    m = DisplayStateMachine()
    assert m.transition_replay(events.EndEvent(session_id="s1")) == []


# ---------------------------------------------------------------------------
# Task metadata / file change summary finalize open streams first
# ---------------------------------------------------------------------------


def test_task_metadata_finalizes_streams_then_renders() -> None:
    from klaude_code.protocol.models import TaskMetadata, TaskMetadataItem

    m = DisplayStateMachine()
    mt = TaskMetadataItem(main_agent=TaskMetadata(model_name="test"))
    cmds = m.transition(events.TaskMetadataEvent(session_id="s1", metadata=mt))
    assert _types(cmds) == ["EndThinkingStream", "EndAssistantStream", "RenderTaskMetadata"]


# ---------------------------------------------------------------------------
# Unknown / unhandled event -> empty command list
# ---------------------------------------------------------------------------


def test_unhandled_event_returns_empty() -> None:
    m = DisplayStateMachine()
    # PromptSuggestionClearedEvent has no branch in _transition.
    assert m.transition(events.PromptSuggestionClearedEvent(session_id="s1")) == []


# ---------------------------------------------------------------------------
# Sub-agent task does not render top-level user messages / streams
# ---------------------------------------------------------------------------


def test_sub_agent_user_message_dropped() -> None:
    m = DisplayStateMachine()
    sub_state = SubAgentState(
        sub_agent_type="explorer",
        sub_agent_desc="look around",
        sub_agent_prompt="prompt",
    )
    _ = m.transition(
        events.TaskStartEvent(
            session_id="sub1",
            model_id="test-model",
            sub_agent_state=sub_state,
            parent_session_id="s1",
        )
    )
    assert m.transition(events.UserMessageEvent(session_id="sub1", content="ignored")) == []


def test_replay_begin_and_end_helpers() -> None:
    m = DisplayStateMachine()
    begin = m.begin_replay()
    end = m.end_replay()
    assert _types(begin) == ["SpinnerStop", "PrintBlankLine"]
    assert _types(end) == ["SpinnerStop"]
