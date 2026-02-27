from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from klaude_code.core.tool.context import ToolContext
from klaude_code.core.tool.tool_abc import ToolABC, load_desc
from klaude_code.core.tool.tool_registry import register
from klaude_code.protocol import llm_param, message, tools, user_interaction


class AskUserQuestionOptionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str
    description: str


class AskUserQuestionQuestionInput(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    question: str
    header: str
    options: list[AskUserQuestionOptionInput] = Field(min_length=2, max_length=4)
    multi_select: bool = Field(default=False, alias="multiSelect")


class AskUserQuestionMetadataInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str | None = None


class AskUserQuestionArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    questions: list[AskUserQuestionQuestionInput] = Field(min_length=1, max_length=4)
    answers: dict[str, str] | None = None
    metadata: AskUserQuestionMetadataInput | None = None


@register(tools.ASK_USER_QUESTION)
class AskUserQuestionTool(ToolABC):
    _BLOCK_SEPARATOR = "\n---\n"

    @classmethod
    def schema(cls) -> llm_param.ToolSchema:
        return llm_param.ToolSchema(
            name=tools.ASK_USER_QUESTION,
            type="function",
            description=load_desc(Path(__file__).parent / "ask_user_question_tool.md"),
            parameters={
                "type": "object",
                "properties": {
                    "questions": {
                        "description": "Questions to ask the user (1-4 questions)",
                        "minItems": 1,
                        "maxItems": 4,
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "question": {"type": "string"},
                                "header": {"type": "string"},
                                "options": {
                                    "type": "array",
                                    "minItems": 2,
                                    "maxItems": 4,
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "label": {"type": "string"},
                                            "description": {"type": "string"},
                                        },
                                        "required": ["label", "description"],
                                        "additionalProperties": False,
                                    },
                                },
                                "multiSelect": {
                                    "type": "boolean",
                                    "default": False,
                                },
                            },
                            "required": ["question", "header", "options", "multiSelect"],
                            "additionalProperties": False,
                        },
                    },
                    "answers": {
                        "description": "User answers collected by the permission component",
                        "type": "object",
                        "propertyNames": {"type": "string"},
                        "additionalProperties": {"type": "string"},
                    },
                    "metadata": {
                        "type": "object",
                        "properties": {
                            "source": {
                                "type": "string",
                            }
                        },
                        "additionalProperties": False,
                    },
                },
                "required": ["questions"],
                "additionalProperties": False,
            },
        )

    @classmethod
    async def call(cls, arguments: str, context: ToolContext) -> message.ToolResultMessage:
        try:
            args = AskUserQuestionArguments.model_validate_json(arguments)
        except ValueError as exc:
            return message.ToolResultMessage(status="error", output_text=f"Invalid arguments: {exc}")

        request_user_interaction = context.request_user_interaction
        if request_user_interaction is None:
            return message.ToolResultMessage(
                status="error",
                output_text="AskUserQuestion is not available in this context",
            )

        interaction_questions: list[user_interaction.AskUserQuestionQuestion] = []
        for q_idx, question in enumerate(args.questions, start=1):
            interaction_options: list[user_interaction.AskUserQuestionOption] = []
            for o_idx, option in enumerate(question.options, start=1):
                interaction_options.append(
                    user_interaction.AskUserQuestionOption(
                        id=f"q{q_idx}_o{o_idx}",
                        label=option.label,
                        description=option.description,
                    )
                )
            interaction_questions.append(
                user_interaction.AskUserQuestionQuestion(
                    id=f"q{q_idx}",
                    header=question.header,
                    question=question.question,
                    options=interaction_options,
                    multi_select=question.multi_select,
                    input_placeholder="Type something.",
                    require_input_when_other_selected=True,
                )
            )

        request_payload = user_interaction.AskUserQuestionRequestPayload(
            questions=interaction_questions,
            metadata=user_interaction.AskUserQuestionMetadata(source=args.metadata.source)
            if args.metadata is not None
            else None,
        )

        try:
            response = await request_user_interaction(
                uuid4().hex,
                "tool",
                request_payload,
                None,
            )
        except asyncio.CancelledError:
            task = asyncio.current_task()
            if task is not None and task.cancelling():
                raise
            return message.ToolResultMessage(
                status="success",
                output_text=cls._format_cancelled_output(interaction_questions),
                continue_agent=False,
            )

        if response.status == "cancelled":
            return message.ToolResultMessage(
                status="success",
                output_text=cls._format_cancelled_output(interaction_questions),
                continue_agent=False,
            )

        if response.payload is None:
            return message.ToolResultMessage(status="error", output_text="Missing AskUserQuestion response payload")

        return message.ToolResultMessage(
            status="success",
            output_text=cls._format_submitted_output(interaction_questions, response.payload.answers),
        )

    @classmethod
    def _format_cancelled_output(
        cls,
        questions: list[user_interaction.AskUserQuestionQuestion],
    ) -> str:
        blocks: list[str] = []
        for question in questions:
            blocks.append(f"Q: {question.question}\nA: User declined to answer questions")
        return cls._BLOCK_SEPARATOR.join(blocks)

    @classmethod
    def _format_submitted_output(
        cls,
        questions: list[user_interaction.AskUserQuestionQuestion],
        answers: list[user_interaction.AskUserQuestionAnswer],
    ) -> str:
        answers_by_question_id = {answer.question_id: answer for answer in answers}
        blocks: list[str] = []

        for question in questions:
            answer = answers_by_question_id.get(question.id)
            if answer is None:
                blocks.append(f"Q: {question.question}\nA: (No answer provided)")
                continue

            option_by_id = {option.id: option for option in question.options}
            selected_lines: list[str] = []
            for option_id in answer.selected_option_ids:
                if option_id == "__other__":
                    other_value = (answer.other_text or answer.note or "").strip()
                    if other_value:
                        selected_lines.append(f"Other: {other_value}")
                    else:
                        selected_lines.append("Other")
                    continue

                option = option_by_id.get(option_id)
                if option is None:
                    continue
                selected_lines.append(f"{option.label} {option.description}".strip())

            if not selected_lines:
                free_text = (answer.note or "").strip()
                if free_text:
                    selected_lines.append(f"Other: {free_text}")

            if question.multi_select:
                if selected_lines:
                    bullet_lines = "\n".join(f"- {line}" for line in selected_lines)
                    blocks.append(f"Q: {question.question}\nA:\n{bullet_lines}")
                else:
                    blocks.append(f"Q: {question.question}\nA: (No answer provided)")
                continue

            single_line = selected_lines[0] if selected_lines else "(No answer provided)"
            blocks.append(f"Q: {question.question}\nA: {single_line}")

        return cls._BLOCK_SEPARATOR.join(blocks)
