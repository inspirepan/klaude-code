from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any, TypeVar

from klaude_code.core.user_interaction import UserInteractionManager
from klaude_code.protocol import events, user_interaction
from klaude_code.protocol.user_interaction import (
    AskUserQuestionOption,
    AskUserQuestionQuestion,
    AskUserQuestionRequestPayload,
    AskUserQuestionResponsePayload,
    UserInteractionResponse,
)

T = TypeVar("T")


def arun[T](coro: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(coro)


def _payload() -> AskUserQuestionRequestPayload:
    return AskUserQuestionRequestPayload(
        questions=[
            AskUserQuestionQuestion(
                id="q1",
                header="Choice",
                question="Pick one?",
                options=[
                    AskUserQuestionOption(id="a", label="A", description="Option A"),
                    AskUserQuestionOption(id="b", label="B", description="Option B"),
                ],
            )
        ]
    )


def test_manager_emits_event_and_resolves_response() -> None:
    async def _test() -> None:
        emitted: list[events.Event] = []

        async def _emit(event: events.Event) -> None:
            emitted.append(event)

        manager = UserInteractionManager(_emit)

        task = asyncio.create_task(
            manager.request(
                request_id="req1",
                session_id="s1",
                source="tool",
                tool_call_id="call1",
                payload=_payload(),
            )
        )
        req = await manager.wait_next_request()
        assert req.request_id == "req1"
        assert isinstance(emitted[0], events.UserInteractionRequestEvent)

        manager.respond(
            request_id="req1",
            session_id="s1",
            response=UserInteractionResponse(
                status="submitted",
                payload=AskUserQuestionResponsePayload(
                    answers=[
                        user_interaction.AskUserQuestionAnswer(
                            question_id="q1",
                            selected_option_ids=["a"],
                            selected_option_labels=["A"],
                            other_text="",
                            note="n1",
                        )
                    ]
                ),
            ),
        )

        result = await task
        assert result.status == "submitted"
        assert result.payload is not None
        assert result.payload.answers[0].selected_option_ids == ["a"]

    arun(_test())


def test_manager_allows_only_single_pending_request() -> None:
    async def _test() -> None:
        async def _emit(_event: events.Event) -> None:
            return None

        manager = UserInteractionManager(_emit)

        first = asyncio.create_task(
            manager.request(
                request_id="req1",
                session_id="s1",
                source="tool",
                payload=_payload(),
                tool_call_id="call1",
            )
        )
        await manager.wait_next_request()

        raised = False
        try:
            await manager.request(
                request_id="req2",
                session_id="s1",
                source="tool",
                payload=_payload(),
                tool_call_id="call2",
            )
        except RuntimeError:
            raised = True
        assert raised

        assert manager.cancel_pending(session_id="s1")
        cancelled = False
        try:
            await first
        except asyncio.CancelledError:
            cancelled = True
        assert cancelled

    arun(_test())


def test_manager_rejects_submitted_without_payload() -> None:
    async def _test() -> None:
        async def _emit(_event: events.Event) -> None:
            return None

        manager = UserInteractionManager(_emit)

        task = asyncio.create_task(
            manager.request(
                request_id="req1",
                session_id="s1",
                source="tool",
                payload=_payload(),
                tool_call_id="call1",
            )
        )
        await manager.wait_next_request()

        raised = False
        try:
            manager.respond(
                request_id="req1",
                session_id="s1",
                response=UserInteractionResponse(status="submitted", payload=None),
            )
        except ValueError:
            raised = True
        assert raised

        assert manager.cancel_pending(session_id="s1")
        cancelled = False
        try:
            await task
        except asyncio.CancelledError:
            cancelled = True
        assert cancelled

    arun(_test())
