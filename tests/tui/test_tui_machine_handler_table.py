from __future__ import annotations

import pytest

from klaude_code.protocol import events
from klaude_code.tui.commands import RenderNotice
from klaude_code.tui.machine import _NOTICE_EVENT_SPECS, DisplayStateMachine, _build_event_handlers

# Event types the machine is expected to dispatch. Pinned so the reflection-built table
# cannot silently lose (or gain) an entry.
EXPECTED_HANDLED_EVENT_NAMES = {
    "WelcomeEvent",
    "WelcomeContextEvent",
    "UserMessageEvent",
    "BashCommandStartEvent",
    "BashCommandOutputDeltaEvent",
    "BashCommandEndEvent",
    "TaskStartEvent",
    "CompactionStartEvent",
    "CompactionEndEvent",
    "ForkCacheHitRateEvent",
    "RewindEvent",
    "DeveloperMessageEvent",
    "SessionTitleChangedEvent",
    "NoticeEvent",
    "AwaySummaryEvent",
    "AwaySummaryStartEvent",
    "AwaySummaryEndEvent",
    "SessionStatsEvent",
    "ContextUsageEvent",
    "ModelChangedEvent",
    "ThinkingChangedEvent",
    "SubAgentModelChangedEvent",
    "CompactModelChangedEvent",
    "FallbackModelConfigWarnEvent",
    "OperationRejectedEvent",
    "StepStartEvent",
    "ThinkingStartEvent",
    "ThinkingDeltaEvent",
    "ThinkingEndEvent",
    "AssistantTextStartEvent",
    "AssistantTextDeltaEvent",
    "AssistantTextEndEvent",
    "ResponseCompleteEvent",
    "ToolCallStartEvent",
    "ToolCallEvent",
    "ToolLongRunningEvent",
    "ToolOutputDeltaEvent",
    "ToolResultEvent",
    "TaskMetadataEvent",
    "TaskFileChangeSummaryEvent",
    "UsageEvent",
    "CacheHitRateEvent",
    "StepEndEvent",
    "TaskFinishEvent",
    "InterruptEvent",
    "ErrorEvent",
    "EndEvent",
}


def test_handler_table_matches_expected_event_types() -> None:
    handled = {event_cls.__name__ for event_cls in DisplayStateMachine._EVENT_HANDLERS}
    assert handled == EXPECTED_HANDLED_EVENT_NAMES


def test_every_handler_method_is_registered() -> None:
    """Each `_handle_<EventName>` method must land in the table under events.<EventName>."""
    for name in vars(DisplayStateMachine):
        if not name.startswith("_handle_"):
            continue
        event_cls = getattr(events, name.removeprefix("_handle_"), None)
        assert isinstance(event_cls, type), f"{name} has no matching event class"
        assert DisplayStateMachine._EVENT_HANDLERS.get(event_cls) is vars(DisplayStateMachine)[name]


def test_notice_spec_events_are_registered() -> None:
    for event_cls in _NOTICE_EVENT_SPECS:
        assert DisplayStateMachine._EVENT_HANDLERS.get(event_cls) is DisplayStateMachine._render_config_notice


def test_handler_without_matching_event_class_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(DisplayStateMachine, "_handle_NotARealEvent", lambda self, e, **kw: [], raising=False)
    with pytest.raises(RuntimeError, match=r"events\.NotARealEvent"):
        _build_event_handlers()


def test_handler_shadowing_a_notice_event_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(DisplayStateMachine, "_handle_ModelChangedEvent", lambda self, e, **kw: [], raising=False)
    with pytest.raises(RuntimeError, match="duplicate"):
        _build_event_handlers()


def test_unhandled_event_type_yields_no_commands() -> None:
    machine = DisplayStateMachine()
    event = events.UserInteractionCancelledEvent(session_id="main", request_id="r1", reason="interrupt")
    assert event.__class__ not in DisplayStateMachine._EVENT_HANDLERS
    assert machine.transition(event) == []


def _notice(event: events.Event) -> events.NoticeEvent:
    cmds = DisplayStateMachine().transition(event)
    assert len(cmds) == 1
    cmd = cmds[0]
    assert isinstance(cmd, RenderNotice)
    return cmd.event


@pytest.mark.parametrize(
    ("event", "expected_content", "expected_style"),
    [
        (events.ModelChangedEvent(session_id="main", model_id="opus"), "Switched to: opus", None),
        (
            events.ModelChangedEvent(session_id="main", model_id="opus", saved_as_default=True),
            "Switched to: opus (saved as default)",
            None,
        ),
        (
            events.ThinkingChangedEvent(session_id="main", previous="off", current="high"),
            "Thinking changed: off -> high",
            None,
        ),
        (
            events.SubAgentModelChangedEvent(session_id="main", sub_agent_type="explore", model_display="haiku"),
            "explore model: haiku",
            None,
        ),
        (
            events.CompactModelChangedEvent(session_id="main", model_display="haiku"),
            "Compact model: haiku",
            None,
        ),
        (
            events.FallbackModelConfigWarnEvent(
                session_id="main",
                sub_agent_type="explore",
                from_model="a",
                from_provider="p1",
                to_model="b",
                to_provider="p2",
                reason="missing key",
            ),
            "explore model fallback: a@p1 -> b@p2 (missing key)",
            "warn",
        ),
        (
            events.FallbackModelConfigWarnEvent(
                session_id="main",
                from_model="a",
                to_model="b",
                reason="missing key",
            ),
            "Model fallback: a -> b (missing key)",
            "warn",
        ),
    ],
)
def test_config_change_notice_text(event: events.Event, expected_content: str, expected_style: str | None) -> None:
    notice = _notice(event)
    assert notice.content == expected_content
    assert notice.style == expected_style
    assert notice.session_id == "main"
