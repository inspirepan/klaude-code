from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Coroutine
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar

from klaude_code.core.control.user_interaction import PendingUserInteractionRequest
from klaude_code.core.tool.ask_user_question_tool import AskUserQuestionTool
from klaude_code.core.tool.context import TodoContext, ToolContext
from klaude_code.protocol import events, user_interaction

T = TypeVar("T")


def arun[T](coro: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(coro)


def _arguments() -> str:
    return json.dumps(
        {
            "questions": [
                {
                    "question": "What should we do?",
                    "header": "Direction",
                    "options": [
                        {"label": "A", "description": "Option A"},
                        {"label": "B", "description": "Option B"},
                    ],
                    "multiSelect": True,
                }
            ]
        }
    )


@dataclass
class _PendingState:
    request: PendingUserInteractionRequest
    future: asyncio.Future[user_interaction.UserInteractionResponse]


class _InteractionHarness:
    def __init__(self, emit_event: Callable[[events.Event], Awaitable[None]]):
        self._emit_event = emit_event
        self._pending: dict[str, _PendingState] = {}
        self._queue: asyncio.Queue[PendingUserInteractionRequest] = asyncio.Queue()

    async def request(
        self,
        *,
        request_id: str,
        session_id: str,
        source: user_interaction.UserInteractionSource,
        payload: user_interaction.UserInteractionRequestPayload,
        tool_call_id: str | None,
    ) -> user_interaction.UserInteractionResponse:
        loop = asyncio.get_running_loop()
        future: asyncio.Future[user_interaction.UserInteractionResponse] = loop.create_future()
        request = PendingUserInteractionRequest(
            request_id=request_id,
            session_id=session_id,
            source=source,
            tool_call_id=tool_call_id,
            payload=payload,
        )
        self._pending[request_id] = _PendingState(request=request, future=future)
        await self._emit_event(
            events.UserInteractionRequestEvent(
                session_id=session_id,
                request_id=request_id,
                source=source,
                tool_call_id=tool_call_id,
                payload=payload,
            )
        )
        self._queue.put_nowait(request)
        return await future

    async def wait_next_request(self) -> PendingUserInteractionRequest:
        while True:
            request = await self._queue.get()
            if request.request_id in self._pending:
                return request

    def respond(
        self,
        *,
        request_id: str,
        session_id: str,
        response: user_interaction.UserInteractionResponse,
    ) -> None:
        pending = self._pending.pop(request_id, None)
        if pending is None:
            raise ValueError("No pending user interaction")
        if pending.request.session_id != session_id:
            raise ValueError("Session mismatch for pending user interaction")
        if not pending.future.done():
            pending.future.set_result(response)

    def cancel_pending(self, *, session_id: str) -> bool:
        cancelled = False
        for request_id, pending in list(self._pending.items()):
            if pending.request.session_id != session_id:
                continue
            cancelled = True
            self._pending.pop(request_id, None)
            if not pending.future.done():
                pending.future.cancel()
        return cancelled


def test_ask_user_question_end_to_end_submitted() -> None:
    async def _test() -> None:
        emitted: list[events.Event] = []

        async def _emit(event: events.Event) -> None:
            emitted.append(event)

        harness = _InteractionHarness(_emit)
        todo_context = TodoContext(get_todos=lambda: [], set_todos=lambda todos: None)

        async def _request(
            request_id: str,
            source: user_interaction.UserInteractionSource,
            payload: user_interaction.UserInteractionRequestPayload,
            tool_call_id: str | None,
        ) -> user_interaction.UserInteractionResponse:
            return await harness.request(
                request_id=request_id,
                session_id="s1",
                source=source,
                payload=payload,
                tool_call_id=tool_call_id,
            )

        context = ToolContext(
            file_tracker={},
            todo_context=todo_context,
            session_id="s1",
            work_dir=Path("/tmp"),
            request_user_interaction=_request,
        )

        task = asyncio.create_task(AskUserQuestionTool.call(_arguments(), context))
        request = await harness.wait_next_request()
        harness.respond(
            request_id=request.request_id,
            session_id=request.session_id,
            response=user_interaction.UserInteractionResponse(
                status="submitted",
                payload=user_interaction.AskUserQuestionResponsePayload(
                    answers=[
                        user_interaction.AskUserQuestionAnswer(
                            question_id="q1",
                            selected_option_ids=["q1_o1"],
                            other_text=None,
                            note="note",
                        )
                    ]
                ),
            ),
        )

        result = await task
        assert result.status == "success"
        assert isinstance(emitted[0], events.UserInteractionRequestEvent)

    arun(_test())


def test_ask_user_question_end_to_end_cancelled_by_manager() -> None:
    async def _test() -> None:
        async def _emit(_event: events.Event) -> None:
            return None

        harness = _InteractionHarness(_emit)
        todo_context = TodoContext(get_todos=lambda: [], set_todos=lambda todos: None)

        async def _request(
            request_id: str,
            source: user_interaction.UserInteractionSource,
            payload: user_interaction.UserInteractionRequestPayload,
            tool_call_id: str | None,
        ) -> user_interaction.UserInteractionResponse:
            return await harness.request(
                request_id=request_id,
                session_id="s1",
                source=source,
                payload=payload,
                tool_call_id=tool_call_id,
            )

        context = ToolContext(
            file_tracker={},
            todo_context=todo_context,
            session_id="s1",
            work_dir=Path("/tmp"),
            request_user_interaction=_request,
        )

        task = asyncio.create_task(AskUserQuestionTool.call(_arguments(), context))
        request = await harness.wait_next_request()
        assert harness.cancel_pending(session_id=request.session_id)

        result = await task
        assert result.status == "success"
        assert result.continue_agent is False
        assert result.output_text == "Question: What should we do?\nAnswer: (User declined to answer questions)"

    arun(_test())
