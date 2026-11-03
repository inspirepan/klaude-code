"""Build typed replies for pending runtime interactions."""

from typing import Literal

from pydantic import BaseModel

from klaude_code.control.user_interaction import PendingUserInteractionRequest
from klaude_code.protocol import user_interaction


class HeadlessRespondRequest(BaseModel):
    action: Literal["approve", "deny", "option", "text"]
    option: int | None = None
    text: str | None = None


def _build_interaction_response(
    request: PendingUserInteractionRequest, payload: HeadlessRespondRequest
) -> user_interaction.UserInteractionResponse:
    interaction = request.payload
    if payload.action == "deny":
        return user_interaction.UserInteractionResponse(status="cancelled", payload=None)
    if payload.action == "approve":
        if request.source == "approval":
            return user_interaction.UserInteractionResponse(status="submitted", payload=None)
        raise ValueError("pending request is not a permission request; answer it with --option N or --text")
    if payload.action == "option":
        if payload.option is None or payload.option < 1:
            raise ValueError("--option requires a 1-based option number")
        if isinstance(interaction, user_interaction.AskUserQuestionRequestPayload):
            if not interaction.questions:
                raise ValueError("pending request has no questions")
            question = interaction.questions[0]
            if payload.option > len(question.options):
                raise ValueError(f"option out of range (1-{len(question.options)})")
            answer = user_interaction.AskUserQuestionAnswer(
                question_id=question.id, selected_option_ids=[question.options[payload.option - 1].id]
            )
            return user_interaction.UserInteractionResponse(
                status="submitted", payload=user_interaction.AskUserQuestionResponsePayload(answers=[answer])
            )
        if payload.option > len(interaction.options):
            raise ValueError(f"option out of range (1-{len(interaction.options)})")
        return user_interaction.UserInteractionResponse(
            status="submitted",
            payload=user_interaction.OperationSelectResponsePayload(
                selected_option_id=interaction.options[payload.option - 1].id
            ),
        )
    if not payload.text or not payload.text.strip():
        raise ValueError("--text requires a non-empty answer")
    if isinstance(interaction, user_interaction.AskUserQuestionRequestPayload):
        if not interaction.questions:
            raise ValueError("pending request has no questions")
        question = interaction.questions[0]
        answer = user_interaction.AskUserQuestionAnswer(
            question_id=question.id, selected_option_ids=["__other__"], other_text=payload.text.strip()
        )
        return user_interaction.UserInteractionResponse(
            status="submitted", payload=user_interaction.AskUserQuestionResponsePayload(answers=[answer])
        )
    raise ValueError("pending request is a choice; pick it with --option N")
