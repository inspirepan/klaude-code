from pathlib import Path

from klaude_code.protocol import events, message
from klaude_code.session.session import Session


def test_thinking_duration_round_trips_into_replay(tmp_path: Path, isolated_home: Path) -> None:
    del isolated_home
    session = Session(work_dir=tmp_path)
    session.conversation_history = [
        message.AssistantMessage(
            response_id="response-1",
            parts=[
                message.ThinkingTextPart(text="reasoning", duration_s=2.5),
                message.TextPart(text="answer"),
            ],
        )
    ]

    serialized = session.conversation_history[0].model_dump_json()
    restored = message.AssistantMessage.model_validate_json(serialized)
    restored_part = restored.parts[0]
    assert isinstance(restored_part, message.ThinkingTextPart)
    assert restored_part.duration_s == 2.5

    session.conversation_history = [restored]
    replay = list(session.get_history_item())
    thinking_end = next(item for item in replay if isinstance(item, events.ThinkingEndEvent))
    assert thinking_end.duration_s == 2.5


def test_old_thinking_history_without_duration_remains_valid() -> None:
    part = message.ThinkingTextPart.model_validate({"type": "thinking_text", "text": "legacy"})
    assert part.duration_s is None


def test_tool_result_replay_keeps_response_id(tmp_path: Path, isolated_home: Path) -> None:
    del isolated_home
    session = Session(work_dir=tmp_path)
    session.conversation_history = [
        message.AssistantMessage(
            response_id="response-1",
            parts=[
                message.ToolCallPart(
                    call_id="call-1",
                    tool_name="Agent",
                    arguments_json="{}",
                )
            ],
        ),
        message.ToolResultMessage(
            call_id="call-1",
            tool_name="Agent",
            status="error",
            output_text="failed before child spawn",
        ),
    ]

    replay = list(session.get_history_item())
    result = next(item for item in replay if isinstance(item, events.ToolResultEvent))
    assert result.response_id == "response-1"
