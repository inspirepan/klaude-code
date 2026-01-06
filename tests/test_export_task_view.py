from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, cast

from klaude_code.protocol import message, model
from klaude_code.session.export import build_export_html


@dataclass(frozen=True)
class _DummySession:
    id: str
    updated_at: float | None
    work_dir: Path
    conversation_history: list[message.HistoryEvent]


def _dummy_session(history: list[message.HistoryEvent]) -> _DummySession:
    return _DummySession(
        id="test-session",
        updated_at=datetime.now().timestamp(),
        work_dir=Path.cwd(),
        conversation_history=history,
    )


def test_export_tasks_hide_steps_when_no_tools() -> None:
    history: list[message.HistoryEvent] = [
        message.UserMessage(parts=[message.TextPart(text="hello")]),
        message.AssistantMessage(parts=[message.TextPart(text="hi")]),
    ]

    html_doc = build_export_html(
        cast(Any, _dummy_session(history)),
        system_prompt="sys",
        tools=[],
        model_name="test-model",
    )

    assert 'class="task"' in html_doc
    assert 'class="task-final"' in html_doc
    assert 'class="task-steps"' not in html_doc


def test_export_task_includes_steps_toggle_when_tools_used() -> None:
    call_id = "call_1"
    history: list[message.HistoryEvent] = [
        message.UserMessage(parts=[message.TextPart(text="run something")]),
        message.AssistantMessage(
            parts=[
                message.TextPart(text="Thinking..."),
                message.ToolCallPart(
                    call_id=call_id,
                    tool_name="Bash",
                    arguments_json='{"command":"echo hi"}',
                ),
            ]
        ),
        message.ToolResultMessage(
            call_id=call_id,
            tool_name="Bash",
            status="success",
            output_text="hi\n",
        ),
        message.AssistantMessage(parts=[message.TextPart(text="done")]),
    ]

    html_doc = build_export_html(
        cast(Any, _dummy_session(history)),
        system_prompt="sys",
        tools=[],
        model_name="test-model",
    )

    assert 'class="task-steps"' in html_doc
    assert 'data-step-count="' in html_doc
    assert 'class="tool-call"' in html_doc


def test_export_mermaid_task_shows_diagram_in_compact_view() -> None:
    call_id = "m1"
    code = 'graph LR\nA["User"] --> B["Agent"]'
    history: list[message.HistoryEvent] = [
        message.UserMessage(parts=[message.TextPart(text="draw")]),
        message.AssistantMessage(
            parts=[
                message.TextPart(text="diagram:"),
                message.ToolCallPart(
                    call_id=call_id,
                    tool_name="Mermaid",
                    arguments_json=json.dumps({"code": code}),
                ),
            ]
        ),
        message.ToolResultMessage(
            call_id=call_id,
            tool_name="Mermaid",
            status="success",
            output_text="",
            ui_extra=model.MermaidLinkUIExtra(code=code, link="https://example.com", line_count=2),
        ),
        message.AssistantMessage(parts=[message.TextPart(text="done")]),
    ]

    html_doc = build_export_html(
        cast(Any, _dummy_session(history)),
        system_prompt="sys",
        tools=[],
        model_name="test-model",
    )

    assert 'class="task-steps"' in html_doc
    assert 'class="task-mermaid-result"' in html_doc

    # Mermaid should appear where the tool call happened (between the two assistant messages).
    mermaid_pos = html_doc.find('class="task-mermaid-result"')
    prev_msg_pos = html_doc.rfind('data-raw="diagram:"', 0, mermaid_pos)
    next_msg_pos = html_doc.find('data-raw="done"', mermaid_pos)
    assert prev_msg_pos != -1
    assert next_msg_pos != -1
    assert prev_msg_pos < mermaid_pos < next_msg_pos
