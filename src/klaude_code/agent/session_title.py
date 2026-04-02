"""Session title generation helpers."""

from __future__ import annotations

import re

from klaude_code.llm.client import LLMClientABC
from klaude_code.log import DebugType, log_debug
from klaude_code.protocol import llm_param, message

_SESSION_TITLE_SYSTEM_PROMPT = (
    "You generate short, specific conversation titles from user messages. "
    "Use the same language as the user's messages and do not translate. "
    "Reply with only the title, no quotes, no markdown, no explanation."
)

_SESSION_TITLE_MAX_TOKENS = 4096


def _build_session_title_input(user_messages: list[str], *, previous_title: str | None = None) -> list[message.Message]:
    current_user_message = user_messages[-1].strip()
    previous_user_messages = [msg.strip() for msg in user_messages[:-1] if msg.strip()]
    rendered_previous_messages = "\n\n".join(
        f"[{idx}] {msg}" for idx, msg in enumerate(previous_user_messages, start=1)
    )
    rendered_previous_title = previous_title.strip() if previous_title is not None else ""
    previous_title_block = (
        f"<previous_title>\n{rendered_previous_title}\n</previous_title>\n\n" if rendered_previous_title else ""
    )
    return [
        message.UserMessage(
            parts=[
                message.TextPart(
                    text=(
                        "Generate a short session title that captures the specific task.\n\n"
                        "Rules:\n"
                        "- be specific: name the concrete thing being done, not the broad area (BAD: 'TUI 开发', GOOD: '修复终端标题截断问题')\n"
                        "- reflect user intent, not tool usage or internal operations\n"
                        "- use the same language as the user's messages; do not translate\n"
                        "- maximum 80 characters; prefer concise phrasing\n"
                        "- single line, imperative or noun phrase, no filler words\n"
                        "- if a previous title exists and the topic hasn't changed, refine it rather than replace it\n\n"
                        f"{previous_title_block}"
                        f"<previous_user_messages>\n{rendered_previous_messages}\n</previous_user_messages>\n\n"
                        f"<current_user_message>\n{current_user_message}\n</current_user_message>"
                    )
                )
            ]
        )
    ]


def _normalize_session_title(raw: str) -> str | None:
    title = " ".join(raw.split()).strip().strip("\"'`“”‘’")
    title = re.sub(r"\s*\|\s*", " — ", title, count=1)
    if not title:
        return None
    return title[:120]


async def generate_session_title(
    *, llm_client: LLMClientABC, user_messages: list[str], previous_title: str | None = None
) -> str | None:
    if not user_messages:
        return None
    title_input = _build_session_title_input(user_messages, previous_title=previous_title)
    call_param = llm_param.LLMCallParameter(
        input=title_input,
        system=_SESSION_TITLE_SYSTEM_PROMPT,
        session_id=None,
    )
    call_param.max_tokens = _SESSION_TITLE_MAX_TOKENS
    call_param.tools = None

    log_debug(
        "[SessionTitle] request",
        message.join_text_parts(title_input[0].parts).replace("\n", "\\n"),
        debug_type=DebugType.RESPONSE,
    )

    stream = await llm_client.call(call_param)
    parts: list[str] = []
    final_text: str | None = None
    stop_reason: str | None = None
    async for item in stream:
        if isinstance(item, message.AssistantTextDelta):
            parts.append(item.content)
        elif isinstance(item, message.AssistantMessage):
            final_text = message.join_text_parts(item.parts)
            stop_reason = item.stop_reason
        elif isinstance(item, message.StreamErrorItem):
            raise RuntimeError(item.error)

    title = _normalize_session_title(final_text if final_text is not None else "".join(parts))
    if stop_reason:
        log_debug(f"[SessionTitle] stop_reason {stop_reason}", debug_type=DebugType.RESPONSE)
    log_debug("[SessionTitle] result", title or "<empty>", debug_type=DebugType.RESPONSE)
    return title
