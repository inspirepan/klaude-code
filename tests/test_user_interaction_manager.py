from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any, TypeVar

from klaude_code.core.user_interaction import PendingUserInteractionRequest, UserInteractionManager
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


def test_manager_allows_multiple_pending_requests() -> None:
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
        second = asyncio.create_task(
            manager.request(
                request_id="req2",
                session_id="s2",
                source="tool",
                payload=_payload(),
                tool_call_id="call2",
            )
        )

        first_request = await manager.wait_next_request()
        second_request = await manager.wait_next_request()
        assert {first_request.request_id, second_request.request_id} == {"req1", "req2"}

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
                            other_text="",
                            note="n1",
                        )
                    ]
                ),
            ),
        )
        manager.respond(
            request_id="req2",
            session_id="s2",
            response=UserInteractionResponse(
                status="submitted",
                payload=AskUserQuestionResponsePayload(
                    answers=[
                        user_interaction.AskUserQuestionAnswer(
                            question_id="q1",
                            selected_option_ids=["b"],
                            other_text="",
                            note="n2",
                        )
                    ]
                ),
            ),
        )

        first_result = await first
        second_result = await second
        assert first_result.status == "submitted"
        assert second_result.status == "submitted"

    arun(_test())


def test_manager_cancel_pending_with_session_filter() -> None:
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
        second = asyncio.create_task(
            manager.request(
                request_id="req2",
                session_id="s2",
                source="tool",
                payload=_payload(),
                tool_call_id="call2",
            )
        )

        await manager.wait_next_request()
        await manager.wait_next_request()

        assert manager.cancel_pending(session_id="s1")
        assert manager.is_pending("req2")

        cancelled = False
        try:
            await first
        except asyncio.CancelledError:
            cancelled = True
        assert cancelled

        manager.respond(
            request_id="req2",
            session_id="s2",
            response=UserInteractionResponse(
                status="submitted",
                payload=AskUserQuestionResponsePayload(
                    answers=[
                        user_interaction.AskUserQuestionAnswer(
                            question_id="q1",
                            selected_option_ids=["b"],
                            other_text="",
                            note="n2",
                        )
                    ]
                ),
            ),
        )
        result = await second
        assert result.status == "submitted"

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


def test_manager_notifies_request_state_changes() -> None:
    async def _test() -> None:
        async def _emit(_event: events.Event) -> None:
            return None

        changes: list[tuple[str, str, bool]] = []

        def _on_state_change(request: PendingUserInteractionRequest, is_pending: bool) -> None:
            changes.append((request.session_id, request.request_id, is_pending))

        manager = UserInteractionManager(_emit, on_request_state_change=_on_state_change)

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
                            other_text="",
                            note="n1",
                        )
                    ]
                ),
            ),
        )
        await task

        assert changes == [("s1", "req1", True), ("s1", "req1", False)]

    arun(_test())
