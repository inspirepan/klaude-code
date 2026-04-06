from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Coroutine
from pathlib import Path
from typing import Any, TypeVar

from klaude_code.protocol import model, user_interaction
from klaude_code.tool.ask_user_question_tool import AskUserQuestionTool
from klaude_code.tool.context import TodoContext, ToolContext

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
        work_dir=Path("/tmp"),
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
        assert payload.kind == "ask_user_question"
        assert payload.questions[0].options[0].id == "q1_o1"
        assert payload.questions[0].options[0].markdown is None
        return user_interaction.UserInteractionResponse(
            status="submitted",
            payload=user_interaction.AskUserQuestionResponsePayload(
                answers=[
                    user_interaction.AskUserQuestionAnswer(
                        question_id="q1",
                        selected_option_ids=["q1_o1", "__other__"],
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
        ]
    }

    result = arun(AskUserQuestionTool.call(json.dumps(arguments), _context(_callback)))
    assert result.status == "success"
    assert result.continue_agent is True
    assert result.output_text == "Question: What should we do?\nAnswer:\n- A: Option A\n- Other: custom"
    assert isinstance(result.ui_extra, model.AskUserQuestionSummaryUIExtra)
    assert result.ui_extra.items[0].summary == "A: Option A\nOther: custom"
    assert result.ui_extra.items[0].answered is True


def test_ask_user_question_single_select_annotation_is_included_for_model_only() -> None:
    async def _callback(
        _request_id: str,
        _source: user_interaction.UserInteractionSource,
        payload: user_interaction.UserInteractionRequestPayload,
        _tool_call_id: str | None,
    ) -> user_interaction.UserInteractionResponse:
        assert payload.kind == "ask_user_question"
        assert payload.questions[0].options[0].markdown == "# Design A\n\nFast path"
        return user_interaction.UserInteractionResponse(
            status="submitted",
            payload=user_interaction.AskUserQuestionResponsePayload(
                answers=[
                    user_interaction.AskUserQuestionAnswer(
                        question_id="q1",
                        selected_option_ids=["q1_o1"],
                        annotation=user_interaction.AskUserQuestionAnswer.Annotation(
                            markdown="# Design A\n\nFast path",
                        ),
                    )
                ]
            ),
        )

    arguments = {
        "questions": [
            {
                "question": "Which design should we ship?",
                "header": "Design",
                "options": [
                    {
                        "label": "A",
                        "description": "Option A",
                        "markdown": "# Design A\n\nFast path",
                    },
                    {"label": "B", "description": "Option B"},
                ],
                "multiSelect": False,
            }
        ]
    }

    result = arun(AskUserQuestionTool.call(json.dumps(arguments), _context(_callback)))
    assert result.status == "success"
    assert result.output_text == (
        "Question: Which design should we ship?\nAnswer: A: Option A\nSelected markdown:\n# Design A\n\nFast path"
    )
    assert isinstance(result.ui_extra, model.AskUserQuestionSummaryUIExtra)
    assert result.ui_extra.items[0].summary == "A: Option A"
    assert result.ui_extra.items[0].answered is True


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
    assert result.output_text == "Question: What should we do?\nAnswer: (User declined to answer questions)"
    assert isinstance(result.ui_extra, model.AskUserQuestionSummaryUIExtra)
    assert result.ui_extra.items[0].summary == "(User declined to answer questions)"
    assert result.ui_extra.items[0].answered is False


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
    assert result.output_text == "Question: Choose one\nAnswer: B: Option B"


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
    assert result.output_text == "Question: 请选择一个选项以确认工具可用：\nAnswer: Other: 自定义内容"


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
    assert result.output_text == ("Question: Q1\nAnswer: A: Option A\n---\nQuestion: Q2\nAnswer: (No answer provided)")
