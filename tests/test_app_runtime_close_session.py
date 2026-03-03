from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any, TypeVar, cast

from klaude_code.core.control.runtime_facade import RuntimeFacade
from klaude_code.core.control.user_interaction import PendingUserInteractionRequest
from klaude_code.protocol import events, user_interaction

T = TypeVar("T")


def arun[T](coro: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(coro)


def _pending_request(request_id: str, session_id: str) -> PendingUserInteractionRequest:
    return PendingUserInteractionRequest(
        request_id=request_id,
        session_id=session_id,
        source="tool",
        tool_call_id=None,
        payload=user_interaction.AskUserQuestionRequestPayload(
            questions=[
                user_interaction.AskUserQuestionQuestion(
                    id="q1",
                    header="h",
                    question="q",
                    options=[
                        user_interaction.AskUserQuestionOption(id="o1", label="A", description="d"),
                        user_interaction.AskUserQuestionOption(id="o2", label="B", description="d"),
                    ],
                )
            ]
        ),
    )


def test_close_session_force_emits_interaction_cancelled_and_resolved_events() -> None:
    class _StubSessionRegistry:
        def __init__(self) -> None:
            self.cancelled = [_pending_request("req1", "s1")]

        def cancel_pending_interactions_with_requests(
            self,
            *,
            session_id: str | None = None,
        ) -> list[PendingUserInteractionRequest]:
            assert session_id == "s1"
            return list(self.cancelled)

        async def close_session(self, session_id: str, *, force: bool = False) -> bool:
            assert session_id == "s1"
            assert force is True
            return True

    class _StubCommandDispatcher:
        def __init__(self) -> None:
            self.events: list[tuple[events.Event, dict[str, str | None]]] = []

        async def emit_event(
            self,
            event: events.Event,
            *,
            operation_id: str | None = None,
            task_id: str | None = None,
            causation_id: str | None = None,
        ) -> None:
            self.events.append(
                (
                    event,
                    {
                        "operation_id": operation_id,
                        "task_id": task_id,
                        "causation_id": causation_id,
                    },
                )
            )

    async def _test() -> None:
        runtime_any = cast(Any, object.__new__(RuntimeFacade))
        runtime_any.session_registry = _StubSessionRegistry()
        runtime_any._command_dispatcher = _StubCommandDispatcher()

        runtime = cast(RuntimeFacade, runtime_any)
        closed = await RuntimeFacade.close_session(runtime, "s1", force=True)
        assert closed is True

        executor = runtime_any._command_dispatcher
        recorded = executor.events
        assert len(recorded) == 2

        first_event, first_meta = recorded[0]
        second_event, second_meta = recorded[1]

        assert isinstance(first_event, events.UserInteractionCancelledEvent)
        assert first_event.request_id == "req1"
        assert first_event.reason == "session_close"
        assert first_meta["causation_id"] == "req1"

        assert isinstance(second_event, events.UserInteractionResolvedEvent)
        assert second_event.request_id == "req1"
        assert second_event.status == "cancelled"
        assert second_meta["causation_id"] == "req1"

    arun(_test())
