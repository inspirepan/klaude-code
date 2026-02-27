from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Coroutine
from typing import Any, TypeVar

from klaude_code.core.tool.ask_user_question_tool import AskUserQuestionTool
from klaude_code.core.tool.context import TodoContext, ToolContext
from klaude_code.protocol import user_interaction

T = TypeVar("T")


def arun[T](coro: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(coro)


def _context(
    callback: (
        Callable[
            [str, user_interaction.UserInteractionSource, user_interaction.UserInteractionRequestPayload, str | None],
            Awaitable[user_interaction.UserInteractionResponse],
        ]
        | None
    ) = None,
) -> ToolContext:
    todo_context = TodoContext(get_todos=lambda: [], set_todos=lambda todos: None)
    return ToolContext(
        file_tracker={},
        todo_context=todo_context,
        session_id="s1",
        request_user_interaction=callback,
    )


def test_ask_user_question_requires_interaction_callback() -> None:
    arguments = {
        "questions": [
            {
                "question": "What should we do?",
                "header": "Direction",
                "options": [
                    {"label": "A", "description": "Option A"},
                    {"label": "B", "description": "Option B"},
                ],
                "multiSelect": False,
            }
        ]
    }
    result = arun(AskUserQuestionTool.call(json.dumps(arguments), _context()))
    assert result.status == "error"
    assert "not available" in result.output_text


def test_ask_user_question_success_response() -> None:
    async def _callback(
        _request_id: str,
        source: user_interaction.UserInteractionSource,
        payload: user_interaction.UserInteractionRequestPayload,
        _tool_call_id: str | None,
    ) -> user_interaction.UserInteractionResponse:
        assert source == "tool"
        assert payload.questions[0].options[0].id == "q1_o1"
        return user_interaction.UserInteractionResponse(
            status="submitted",
            payload=user_interaction.AskUserQuestionResponsePayload(
                answers=[
                    user_interaction.AskUserQuestionAnswer(
                        question_id="q1",
                        selected_option_ids=["q1_o1", "__other__"],
                        selected_option_labels=["A", "Other"],
                        other_text="custom",
                        note="extra",
                    )
                ]
            ),
        )

    arguments = {
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
        ],
        "metadata": {"source": "plan"},
    }

    result = arun(AskUserQuestionTool.call(json.dumps(arguments), _context(_callback)))
    assert result.status == "success"
    assert result.continue_agent is True
    assert result.output_text == "Q: What should we do?\nA:\n- A Option A\n- Other: custom"


def test_ask_user_question_cancelled_response_returns_aborted() -> None:
    async def _callback(
        _request_id: str,
        _source: user_interaction.UserInteractionSource,
        _payload: user_interaction.UserInteractionRequestPayload,
        _tool_call_id: str | None,
    ) -> user_interaction.UserInteractionResponse:
        return user_interaction.UserInteractionResponse(status="cancelled", payload=None)

    arguments = {
        "questions": [
            {
                "question": "What should we do?",
                "header": "Direction",
                "options": [
                    {"label": "A", "description": "Option A"},
                    {"label": "B", "description": "Option B"},
                ],
                "multiSelect": False,
            }
        ]
    }

    result = arun(AskUserQuestionTool.call(json.dumps(arguments), _context(_callback)))
    assert result.status == "success"
    assert result.continue_agent is False
    assert result.output_text == "Q: What should we do?\nA: (User declined to answer questions)"


def test_ask_user_question_single_select_format() -> None:
    async def _callback(
        _request_id: str,
        _source: user_interaction.UserInteractionSource,
        _payload: user_interaction.UserInteractionRequestPayload,
        _tool_call_id: str | None,
    ) -> user_interaction.UserInteractionResponse:
        return user_interaction.UserInteractionResponse(
            status="submitted",
            payload=user_interaction.AskUserQuestionResponsePayload(
                answers=[
                    user_interaction.AskUserQuestionAnswer(
                        question_id="q1",
                        selected_option_ids=["q1_o2"],
                        selected_option_labels=["B"],
                        other_text=None,
                        note=None,
                    )
                ]
            ),
        )

    arguments = {
        "questions": [
            {
                "question": "Choose one",
                "header": "Direction",
                "options": [
                    {"label": "A", "description": "Option A"},
                    {"label": "B", "description": "Option B"},
                ],
                "multiSelect": False,
            }
        ]
    }

    result = arun(AskUserQuestionTool.call(json.dumps(arguments), _context(_callback)))
    assert result.status == "success"
    assert result.output_text == "Q: Choose one\nA: B Option B"


def test_ask_user_question_input_only_formats_as_other() -> None:
    async def _callback(
        _request_id: str,
        _source: user_interaction.UserInteractionSource,
        _payload: user_interaction.UserInteractionRequestPayload,
        _tool_call_id: str | None,
    ) -> user_interaction.UserInteractionResponse:
        return user_interaction.UserInteractionResponse(
            status="submitted",
            payload=user_interaction.AskUserQuestionResponsePayload(
                answers=[
                    user_interaction.AskUserQuestionAnswer(
                        question_id="q1",
                        selected_option_ids=[],
                        selected_option_labels=[],
                        other_text=None,
                        note="自定义内容",
                    )
                ]
            ),
        )

    arguments = {
        "questions": [
            {
                "question": "请选择一个选项以确认工具可用：",
                "header": "Direction",
                "options": [
                    {"label": "A", "description": "Option A"},
                    {"label": "B", "description": "Option B"},
                ],
                "multiSelect": False,
            }
        ]
    }

    result = arun(AskUserQuestionTool.call(json.dumps(arguments), _context(_callback)))
    assert result.status == "success"
    assert result.output_text == "Q: 请选择一个选项以确认工具可用：\nA: Other: 自定义内容"


def test_ask_user_question_missing_answer_and_separator_format() -> None:
    async def _callback(
        _request_id: str,
        _source: user_interaction.UserInteractionSource,
        _payload: user_interaction.UserInteractionRequestPayload,
        _tool_call_id: str | None,
    ) -> user_interaction.UserInteractionResponse:
        return user_interaction.UserInteractionResponse(
            status="submitted",
            payload=user_interaction.AskUserQuestionResponsePayload(
                answers=[
                    user_interaction.AskUserQuestionAnswer(
                        question_id="q1",
                        selected_option_ids=["q1_o1"],
                        selected_option_labels=["A"],
                        other_text=None,
                        note=None,
                    )
                ]
            ),
        )

    arguments = {
        "questions": [
            {
                "question": "Q1",
                "header": "H1",
                "options": [
                    {"label": "A", "description": "Option A"},
                    {"label": "B", "description": "Option B"},
                ],
                "multiSelect": False,
            },
            {
                "question": "Q2",
                "header": "H2",
                "options": [
                    {"label": "C", "description": "Option C"},
                    {"label": "D", "description": "Option D"},
                ],
                "multiSelect": False,
            },
        ]
    }

    result = arun(AskUserQuestionTool.call(json.dumps(arguments), _context(_callback)))
    assert result.status == "success"
    assert result.output_text == "Q: Q1\nA: A Option A\n---\nQ: Q2\nA: (No answer provided)"
