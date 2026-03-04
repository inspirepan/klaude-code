from __future__ import annotations

import json

from klaude_code.protocol import message

from .conftest import AppEnv, collect_events_until, extract_text, usage, wait_for_event


def test_ask_user_question_flow(app_env: AppEnv) -> None:
    ask_args = {
        "questions": [
            {
                "question": "Which option?",
                "header": "Pick",
                "options": [
                    {"label": "A", "description": "choose A"},
                    {"label": "B", "description": "choose B"},
                ],
                "multiSelect": False,
            }
        ]
    }
    app_env.fake_llm.enqueue(
        message.AssistantMessage(
            parts=[
                message.ToolCallPart(
                    call_id="call-1",
                    tool_name="AskUserQuestion",
                    arguments_json=json.dumps(ask_args, ensure_ascii=False),
                )
            ],
            stop_reason="tool_use",
            usage=usage(input_tokens=11, output_tokens=2),
        )
    )
    app_env.fake_llm.enqueue(
        message.AssistantTextDelta(content="You chose A"),
        message.AssistantMessage(
            parts=[message.TextPart(text="You chose A")],
            stop_reason="stop",
            usage=usage(input_tokens=7, output_tokens=3),
        ),
    )

    session_id = app_env.create_session()
    with app_env.client.websocket_connect(f"/api/sessions/{session_id}/ws") as websocket:
        assert websocket.receive_json()["event_type"] == "usage.snapshot"
        websocket.send_json({"type": "message", "text": "ask me"})

        interaction_event = wait_for_event(websocket, "user.interaction.request")
        request_id = interaction_event["event"]["request_id"]
        websocket.send_json(
            {
                "type": "respond",
                "request_id": request_id,
                "status": "submitted",
                "payload": {
                    "kind": "ask_user_question",
                    "answers": [
                        {
                            "question_id": "q1",
                            "selected_option_ids": ["q1_o1"],
                        }
                    ],
                },
            }
        )
        events = collect_events_until(websocket, "task.finish")

    assert extract_text(events) == "You chose A"
