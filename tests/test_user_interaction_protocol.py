from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any, TypeVar, cast

from klaude_code.protocol import events, op
from klaude_code.protocol.user_interaction import (
    AskUserQuestionAnswer,
    AskUserQuestionOption,
    AskUserQuestionQuestion,
    AskUserQuestionRequestPayload,
    AskUserQuestionResponsePayload,
    OperationSelectOption,
    OperationSelectRequestPayload,
    OperationSelectResponsePayload,
    UserInteractionResponse,
)

T = TypeVar("T")


def arun[T](coro: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(coro)


def test_user_interaction_request_event_model() -> None:
    payload = AskUserQuestionRequestPayload(
        questions=[
            AskUserQuestionQuestion(
                id="q1",
                header="Approach",
                question="Which approach should we use?",
                options=[
                    AskUserQuestionOption(id="a", label="A", description="Option A"),
                    AskUserQuestionOption(id="b", label="B", description="Option B"),
                ],
                multi_select=False,
            )
        ]
    )

    event = events.UserInteractionRequestEvent(
        session_id="s1",
        request_id="req1",
        source="tool",
        tool_call_id="call1",
        payload=payload,
    )

    assert event.request_id == "req1"
    assert event.payload.kind == "ask_user_question"
    assert event.payload.questions[0].options[0].id == "a"


def test_user_interaction_response_submitted_and_cancelled() -> None:
    submitted = UserInteractionResponse(
        status="submitted",
        payload=AskUserQuestionResponsePayload(
            answers=[
                AskUserQuestionAnswer(
                    question_id="q1",
                    selected_option_ids=["a"],
                    other_text="",
                    note="n1",
                    annotation=AskUserQuestionAnswer.Annotation(markdown="## preview"),
                )
            ]
        ),
    )
    assert submitted.status == "submitted"
    assert submitted.payload is not None
    assert submitted.payload.kind == "ask_user_question"
    assert submitted.payload.answers[0].question_id == "q1"
    assert submitted.payload.answers[0].annotation is not None
    assert submitted.payload.answers[0].annotation.markdown == "## preview"

    cancelled = UserInteractionResponse(status="cancelled", payload=None)
    assert cancelled.status == "cancelled"
    assert cancelled.payload is None


def test_operation_select_payload_model() -> None:
    payload = OperationSelectRequestPayload(
        header="Model",
        question="Select a model",
        options=[
            OperationSelectOption(id="openai@gpt-5", label="openai@gpt-5", description="openai / gpt-5"),
            OperationSelectOption(
                id="anthropic@claude-sonnet-4",
                label="anthropic@claude-sonnet-4",
                description="anthropic / claude-sonnet-4",
            ),
        ],
    )
    event = events.UserInteractionRequestEvent(
        session_id="s1",
        request_id="req-op-1",
        source="operation_model",
        payload=payload,
    )
    assert event.payload.kind == "operation_select"
    assert event.payload.options[0].id == "openai@gpt-5"

    response = UserInteractionResponse(
        status="submitted",
        payload=OperationSelectResponsePayload(selected_option_id="openai@gpt-5"),
    )
    assert response.payload is not None
    assert response.payload.kind == "operation_select"
    assert response.payload.selected_option_id == "openai@gpt-5"


def test_user_interaction_respond_operation_executes_handler() -> None:
    called: dict[str, bool] = {"ok": False}

    class _Handler:
        async def handle_user_interaction_respond(self, operation: op.UserInteractionRespondOperation) -> None:
            assert operation.request_id == "req1"
            called["ok"] = True

    operation = op.UserInteractionRespondOperation(
        session_id="s1",
        request_id="req1",
        response=UserInteractionResponse(status="cancelled", payload=None),
    )

    arun(operation.execute(cast(Any, _Handler())))
    assert called["ok"]
