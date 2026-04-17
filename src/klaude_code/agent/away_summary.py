"""Away-summary ("while you were away" recap) generator.

Given a session, ask a small/fast LLM for a 1-3 sentence recap of where the
user left off. Mirrors `session_title.generate_session_title` in spirit:
one-shot non-streaming call, single synthesized user message, no tools.
"""

from __future__ import annotations

import asyncio
import re

from klaude_code.agent.compaction.compaction import serialize_conversation
from klaude_code.llm.client import LLMClientABC
from klaude_code.log import DebugType, log_debug
from klaude_code.protocol import llm_param, message
from klaude_code.session.session import Session

_AWAY_SUMMARY_SYSTEM_PROMPT = (
    "You summarize an in-progress coding session for a user who stepped away. "
    "Write a neutral recap, not an evaluation. Do not praise, judge, agree "
    "with, or endorse any proposal. Do not speak in first person as the "
    "assistant, and do not say things like 'I will' or 'I'll'. "
    "Always reply in the exact same natural language the user used in their "
    "own messages (the lines marked [User]:). Never translate. Ignore the "
    "language of assistant replies, tool calls, and tool output when choosing "
    "your output language. "
    "Respond with only the recap text, no quotes, no markdown, no preamble."
)

_AWAY_SUMMARY_MAX_TOKENS = 512

# Recap only needs recent context — truncate to avoid "prompt too long" on
# large sessions. 30 turn messages is plenty for "where we left off."
_RECENT_MESSAGE_WINDOW = 30


def _build_away_summary_user_message(transcript: str) -> message.UserMessage:
    body = (
        "Language rule (highest priority): detect the natural language used "
        "in the [User]: lines below and write your entire reply in that "
        "language. If the user wrote Chinese, reply in Chinese; if Japanese, "
        "reply in Japanese; and so on. Do not translate to English.\n\n"
        "The user stepped away and is coming back. Write exactly 1-3 short "
        "sentences. Start by stating the high-level task — what they are "
        "building or debugging, not implementation details. Then state the "
        "current progress or where the work stopped in one concrete phrase. "
        "End with the concrete next step. Skip status reports and commit "
        "recaps. Write a neutral reminder of where the work stands. Do not "
        "evaluate the quality of ideas, do not repeat encouragement or "
        "approval, do not present a numbered plan, and do not write from the "
        "assistant's point of view. Never say 'I', 'I'll', or 'I will'.\n\n"
        f"<conversation>\n{transcript}\n</conversation>"
    )
    return message.UserMessage(parts=[message.TextPart(text=body)])


def _recent_turn_messages(session: Session, limit: int) -> list[message.Message]:
    """Pull the last `limit` turn messages (user/assistant/tool_result)."""

    turns: list[message.Message] = []
    for item in reversed(session.conversation_history):
        if isinstance(item, (message.UserMessage, message.AssistantMessage, message.ToolResultMessage)):
            turns.append(item)
            if len(turns) >= limit:
                break
    turns.reverse()
    return turns


def _normalize_recap(raw: str) -> str | None:
    text = raw.strip().strip("\"'`“”‘’")
    text = re.sub(r"\s+\n", "\n", text)
    if not text:
        return None
    return text


async def generate_away_summary(
    *,
    llm_client: LLMClientABC,
    session: Session,
    cancel: asyncio.Event | None = None,
) -> str | None:
    """Generate a short away-summary text. Returns None on empty session,
    abort, or error — never raises."""

    turns = _recent_turn_messages(session, _RECENT_MESSAGE_WINDOW)
    if not turns:
        return None

    transcript = serialize_conversation(turns)
    if not transcript.strip():
        return None

    call_param = llm_param.LLMCallParameter(
        input=[_build_away_summary_user_message(transcript)],
        system=_AWAY_SUMMARY_SYSTEM_PROMPT,
        session_id=None,
    )
    call_param.max_tokens = _AWAY_SUMMARY_MAX_TOKENS
    call_param.tools = None

    log_debug("[AwaySummary] request", f"turns={len(turns)}", debug_type=DebugType.RESPONSE)

    if cancel is not None and cancel.is_set():
        return None

    try:
        stream = await llm_client.call(call_param)
        accumulated: list[str] = []
        final_text: str | None = None
        async for item in stream:
            if isinstance(item, message.AssistantTextDelta):
                accumulated.append(item.content)
            elif isinstance(item, message.AssistantMessage):
                final_text = message.join_text_parts(item.parts)
            elif isinstance(item, message.StreamErrorItem):
                log_debug(f"[AwaySummary] stream error: {item.error}", debug_type=DebugType.RESPONSE)
                return None
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        log_debug(f"[AwaySummary] generation failed: {exc}", debug_type=DebugType.RESPONSE)
        return None

    if cancel is not None and cancel.is_set():
        return None

    raw = final_text if final_text is not None else "".join(accumulated)
    recap = _normalize_recap(raw)
    log_debug("[AwaySummary] result", recap or "<empty>", debug_type=DebugType.RESPONSE)
    return recap
