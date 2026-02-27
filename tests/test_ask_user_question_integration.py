from __future__ import annotations

import asyncio
import json
from collections.abc import Coroutine
from typing import Any, TypeVar

from klaude_code.core.tool.ask_user_question_tool import AskUserQuestionTool
from klaude_code.core.tool.context import TodoContext, ToolContext
from klaude_code.core.user_interaction import UserInteractionManager
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


def test_ask_user_question_end_to_end_submitted() -> None:
    async def _test() -> None:
        emitted: list[events.Event] = []

        async def _emit(event: events.Event) -> None:
            emitted.append(event)

        manager = UserInteractionManager(_emit)
        todo_context = TodoContext(get_todos=lambda: [], set_todos=lambda todos: None)

        async def _request(
            request_id: str,
            source: user_interaction.UserInteractionSource,
            payload: user_interaction.UserInteractionRequestPayload,
            tool_call_id: str | None,
        ) -> user_interaction.UserInteractionResponse:
            return await manager.request(
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
            request_user_interaction=_request,
        )

        task = asyncio.create_task(AskUserQuestionTool.call(_arguments(), context))
        request = await manager.wait_next_request()
        manager.respond(
            request_id=request.request_id,
            session_id=request.session_id,
            response=user_interaction.UserInteractionResponse(
                status="submitted",
                payload=user_interaction.AskUserQuestionResponsePayload(
                    answers=[
                        user_interaction.AskUserQuestionAnswer(
                            question_id="q1",
                            selected_option_ids=["q1_o1"],
                            selected_option_labels=["A"],
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

        manager = UserInteractionManager(_emit)
        todo_context = TodoContext(get_todos=lambda: [], set_todos=lambda todos: None)

        async def _request(
            request_id: str,
            source: user_interaction.UserInteractionSource,
            payload: user_interaction.UserInteractionRequestPayload,
            tool_call_id: str | None,
        ) -> user_interaction.UserInteractionResponse:
            return await manager.request(
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
            request_user_interaction=_request,
        )

        task = asyncio.create_task(AskUserQuestionTool.call(_arguments(), context))
        request = await manager.wait_next_request()
        assert manager.cancel_pending(session_id=request.session_id)

        result = await task
        assert result.status == "success"
        assert result.continue_agent is False
        assert result.output_text == "Q: What should we do?\nA: (User declined to answer questions)"

    arun(_test())
