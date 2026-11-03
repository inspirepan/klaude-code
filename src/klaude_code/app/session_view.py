"""Shared read-only history and interaction presentation."""

from typing import Any, Literal

from pydantic import BaseModel

from klaude_code.app.scheduler import format_tool_call_activity
from klaude_code.control.user_interaction import PendingUserInteractionRequest
from klaude_code.protocol import message, user_interaction
from klaude_code.session.ledger import is_auto_user_message


def serialize_pending_request(request: PendingUserInteractionRequest) -> dict[str, Any]:
    payload = request.payload
    if isinstance(payload, user_interaction.AskUserQuestionRequestPayload):
        first = payload.questions[0] if payload.questions else None
        return {
            "request_id": request.request_id,
            "source_session_id": request.session_id,
            "type": "question",
            "prompt": first.question if first is not None else "",
            "options": [
                {"index": index, "label": option.label, "description": option.description}
                for index, option in enumerate(first.options if first is not None else [], start=1)
            ],
            "multi_select": first.multi_select if first is not None else False,
            "question_count": len(payload.questions),
        }
    return {
        "request_id": request.request_id,
        "source_session_id": request.session_id,
        "type": "choice",
        "prompt": payload.question,
        "options": [
            {"index": index, "label": option.label, "description": option.description}
            for index, option in enumerate(payload.options, start=1)
        ],
        "multi_select": False,
        "question_count": 1,
    }


def _last_assistant_text(history: list[message.HistoryEvent]) -> str:
    for item in reversed(history):
        if isinstance(item, message.AssistantMessage):
            text = message.join_text_parts(item.parts)
            if text.strip():
                return text
    return ""


class BriefToolCall(BaseModel):
    call_id: str
    activity: str
    status: Literal["pending", "success", "error", "aborted"]


class BriefTurnActivity(BaseModel):
    last_user_message: str = ""
    recent_tool_calls: list[BriefToolCall] = []
    recent_assistant_messages: list[str] = []
    assistant_streaming: bool = False


def _brief_turn_activity(history: list[message.HistoryEvent], *, streaming_text: str = "") -> BriefTurnActivity:
    """Summarize the latest user turn without including tool output or reasoning."""
    activity = BriefTurnActivity()
    results: dict[str, message.ToolResultMessage] = {}
    for item in reversed(history):
        if isinstance(item, message.UserMessage) and not is_auto_user_message(item):
            text = message.join_text_parts(item.parts)
            text = " ".join(text.split())
            activity.last_user_message = text[:299] + "…" if len(text) > 300 else text
            break
        if isinstance(item, message.ToolResultMessage):
            results[item.call_id] = item
        elif isinstance(item, message.AssistantMessage):
            text = message.join_text_parts(item.parts)
            if text.strip() and len(activity.recent_assistant_messages) < 5:
                activity.recent_assistant_messages.append(text)
            for part in reversed(item.parts):
                if isinstance(part, message.ToolCallPart) and len(activity.recent_tool_calls) < 5:
                    result = results.get(part.call_id)
                    activity.recent_tool_calls.append(
                        BriefToolCall(
                            call_id=part.call_id,
                            activity=format_tool_call_activity(part.tool_name, part.arguments_json, max_len=120),
                            status=result.status if result is not None else "pending",
                        )
                    )
    activity.recent_tool_calls.reverse()
    activity.recent_assistant_messages.reverse()
    if streaming_text.strip():
        activity.recent_assistant_messages = [*activity.recent_assistant_messages, streaming_text][-5:]
        activity.assistant_streaming = True
    for index, text in enumerate(activity.recent_assistant_messages[:-1]):
        if len(text) > 300:
            marker = "\n… [middle truncated] …\n"
            keep = (300 - len(marker)) // 2
            activity.recent_assistant_messages[index] = text[:keep] + marker + text[-keep:]
    return activity


def _render_transcript_items(history: list[message.HistoryEvent]) -> list[str]:
    blocks: list[str] = []
    for item in history:
        if isinstance(item, message.UserMessage):
            text = message.join_text_parts(item.parts)
            if text.strip():
                blocks.append(f"user> {text}")
        elif isinstance(item, message.AssistantMessage):
            text = message.join_text_parts(item.parts)
            if text.strip():
                blocks.append(text)
            for part in item.parts:
                if isinstance(part, message.ToolCallPart):
                    blocks.append(f"[{format_tool_call_activity(part.tool_name, part.arguments_json, max_len=120)}]")
        elif isinstance(item, message.ToolResultMessage):
            result = " ".join(item.output_text.split())
            if len(result) > 200:
                result = result[:199] + "…"
            if result:
                blocks.append(f"  -> {result}")
    return blocks


def _render_turns(history: list[message.HistoryEvent], turns: int) -> str:
    """Render the last N user+assistant turns as plain text."""
    turn_starts = [
        index
        for index, item in enumerate(history)
        if isinstance(item, message.UserMessage) and item.source != "bash_mode"
    ]
    if not turn_starts:
        return "\n\n".join(_render_transcript_items(history))
    start = turn_starts[-turns] if turns <= len(turn_starts) else 0
    return "\n\n".join(_render_transcript_items(history[start:]))
