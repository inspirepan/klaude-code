from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

type UserInteractionSource = Literal[
    "tool",
    "approval",
    "operation_model",
    "operation_thinking",
    "operation_sub_agent_model",
]


class AskUserQuestionOption(BaseModel):
    id: str
    label: str
    description: str
    markdown: str | None = None


class AskUserQuestionQuestion(BaseModel):
    id: str
    header: str
    question: str
    options: list[AskUserQuestionOption]
    multi_select: bool = False
    input_placeholder: str | None = None


class AskUserQuestionRequestPayload(BaseModel):
    kind: Literal["ask_user_question"] = "ask_user_question"
    questions: list[AskUserQuestionQuestion]


class OperationSelectOption(BaseModel):
    id: str
    label: str
    description: str


class OperationSelectRequestPayload(BaseModel):
    kind: Literal["operation_select"] = "operation_select"
    header: str
    question: str
    options: list[OperationSelectOption]
    input_placeholder: str | None = None


type UserInteractionRequestPayload = AskUserQuestionRequestPayload | OperationSelectRequestPayload


class AskUserQuestionAnswer(BaseModel):
    class Annotation(BaseModel):
        markdown: str | None = None
        notes: str | None = None

    question_id: str
    selected_option_ids: list[str]
    other_text: str | None = None
    note: str | None = None
    annotation: Annotation | None = None


class AskUserQuestionResponsePayload(BaseModel):
    kind: Literal["ask_user_question"] = "ask_user_question"
    answers: list[AskUserQuestionAnswer]


class OperationSelectResponsePayload(BaseModel):
    kind: Literal["operation_select"] = "operation_select"
    selected_option_id: str


type UserInteractionResponsePayload = AskUserQuestionResponsePayload | OperationSelectResponsePayload


class UserInteractionResponse(BaseModel):
    status: Literal["submitted", "cancelled"]
    payload: UserInteractionResponsePayload | None = None
