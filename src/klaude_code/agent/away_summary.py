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
from klaude_code.prompts.away_summary import AWAY_SUMMARY_SYSTEM_PROMPT, AWAY_SUMMARY_USER_PROMPT
from klaude_code.protocol import llm_param, message
from klaude_code.session.session import Session

_AWAY_SUMMARY_MAX_TOKENS = 512

# Recap only needs recent context — truncate to avoid "prompt too long" on
# large sessions. 30 turn messages is plenty for "where we left off."
_RECENT_MESSAGE_WINDOW = 30


def _build_away_summary_user_message(transcript: str) -> message.UserMessage:
    body = AWAY_SUMMARY_USER_PROMPT.format(transcript=transcript)
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
        system=AWAY_SUMMARY_SYSTEM_PROMPT,
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
