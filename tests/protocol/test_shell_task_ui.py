import json
from pathlib import Path

import pytest

from klaude_code.llm.openai_compatible.client import build_payload
from klaude_code.protocol import events, llm_param, message, tools
from klaude_code.protocol.models import MultiUIExtra, ShellTaskUIExtra
from klaude_code.protocol.shell_task import ShellTaskSnapshot
from klaude_code.session.codec import decode_jsonl_line, encode_jsonl_line


@pytest.fixture
def ui_extra() -> ShellTaskUIExtra:
    return ShellTaskUIExtra(
        action="output",
        tasks=[
            ShellTaskSnapshot(
                task_id="0123456789abcdef0123456789abcdef",
                session_id="ui-only-session-id",
                command="ui-only-command",
                description="Build package",
                work_dir="/ui-only-work-dir",
                status="failed",
                background=True,
                started_at=1234.5,
                ended_at=1235.5,
                exit_code=7,
                output_path="/ui-only-output.log",
                reason="ui-only-reason",
                pid=12345,
                output_expired=True,
            )
        ],
        output="  raw output\n",
        next_offset=13,
        truncated=True,
    )


@pytest.mark.parametrize("multi", [False, True])
def test_shell_task_ui_survives_session_codec_and_event_roundtrip(ui_extra: ShellTaskUIExtra, multi: bool) -> None:
    extra = MultiUIExtra(items=[ui_extra]) if multi else ui_extra
    result = message.ToolResultMessage(
        call_id="call-shell",
        tool_name=tools.MANAGE_SHELL,
        status="success",
        output_text="Task summary",
        ui_extra=extra,
    )
    decoded = decode_jsonl_line(encode_jsonl_line(result))
    assert isinstance(decoded, message.ToolResultMessage)
    assert decoded.ui_extra == extra
    event = events.ToolResultEvent(
        session_id="event-session",
        tool_call_id=result.call_id,
        tool_name=result.tool_name,
        status=result.status,
        result=result.output_text,
        ui_extra=extra,
    )
    restored = events.ToolResultEvent.model_validate_json(event.model_dump_json())
    assert restored.ui_extra == extra


def test_shell_task_ui_stays_out_of_real_provider_payload(ui_extra: ShellTaskUIExtra, isolated_home: Path) -> None:
    del isolated_home
    text = f"Task {ui_extra.tasks[0].task_id} [failed, exit 7]: Build package\nOutput:\n  raw output\n"
    result = message.ToolResultMessage(
        call_id="call-shell", tool_name=tools.MANAGE_SHELL, status="success", output_text=text, ui_extra=ui_extra
    )
    payload, _ = build_payload(
        llm_param.LLMCallParameter(
            model_id="deepseek-v4-flash",
            input=[
                message.AssistantMessage(
                    parts=[
                        message.ToolCallPart(
                            call_id=result.call_id, tool_name=tools.MANAGE_SHELL, arguments_json='{"action":"list"}'
                        )
                    ]
                ),
                result,
            ],
        )
    )
    wire_messages = list(payload["messages"])
    assert wire_messages[-1] == {"role": "tool", "tool_call_id": result.call_id, "content": text}
    wire = json.dumps(payload)
    assert ui_extra.tasks[0].task_id in wire
    assert "ui-only" not in wire
    for field in ("ui_extra", "shell_task", "session_id", "started_at", "ended_at", "background", "pid"):
        assert field not in wire
    assert result.ui_extra == ui_extra
