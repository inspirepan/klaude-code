from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

type UserInteractionSource = Literal["tool", "approval"]


class AskUserQuestionOption(BaseModel):
    id: str
    label: str
    description: str


class AskUserQuestionQuestion(BaseModel):
    id: str
    header: str
    question: str
    options: list[AskUserQuestionOption]
    multi_select: bool = False
    input_placeholder: str | None = None
    require_input_when_other_selected: bool = True


class AskUserQuestionMetadata(BaseModel):
    source: str | None = None


class AskUserQuestionRequestPayload(BaseModel):
    kind: Literal["ask_user_question"] = "ask_user_question"
    questions: list[AskUserQuestionQuestion]
    metadata: AskUserQuestionMetadata | None = None


type UserInteractionRequestPayload = AskUserQuestionRequestPayload


class AskUserQuestionAnswer(BaseModel):
    question_id: str
    selected_option_ids: list[str]
    selected_option_labels: list[str]
    other_text: str | None = None
    note: str | None = None


class AskUserQuestionResponsePayload(BaseModel):
    kind: Literal["ask_user_question"] = "ask_user_question"
    answers: list[AskUserQuestionAnswer]


type UserInteractionResponsePayload = AskUserQuestionResponsePayload


class UserInteractionResponse(BaseModel):
    status: Literal["submitted", "cancelled"]
    payload: UserInteractionResponsePayload | None = None
