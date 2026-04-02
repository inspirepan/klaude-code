from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from klaude_code.agent.compaction.compaction import (
    CompactionResult,
    collect_file_operations,
    collect_kept_items_brief,
    collect_messages,
    estimate_history_tokens,
    format_file_operations,
    get_last_context_tokens,
    serialize_conversation,
)
from klaude_code.const import (
    INITIAL_RETRY_DELAY_S,
    MAX_FAILED_TURN_RETRIES,
    MAX_RETRY_DELAY_S,
)
from klaude_code.llm import LLMClientABC
from klaude_code.protocol import llm_param, message

from .prompts import HANDOFF_EXTRACTION_PROMPT, HANDOFF_SUMMARY_PREFIX, HANDOFF_SYSTEM_PROMPT

if TYPE_CHECKING:
    from klaude_code.session.session import Session


async def run_handoff(
    *,
    session: Session,
    goal: str,
    llm_client: LLMClientABC,
    llm_config: llm_param.LLMConfigParameter,
    cancel: asyncio.Event | None = None,
) -> CompactionResult:
    """Run a handoff: extract key context from entire conversation and start fresh.

    Returns a CompactionResult with first_kept_index set to discard all history,
    keeping only the extracted summary.
    """
    del llm_config
    if cancel is not None and cancel.is_set():
        raise asyncio.CancelledError

    history = session.conversation_history
    if not history:
        raise ValueError("No conversation history to hand off")

    tokens_before = get_last_context_tokens(session)
    if tokens_before is None:
        tokens_before = estimate_history_tokens(history)

    # Use LLM-facing history (includes compaction summary) rather than raw history,
    # so previously compacted context is not lost.
    llm_history = session.get_llm_history()
    llm_messages = [item for item in llm_history if isinstance(item, message.Message)]
    if not llm_messages:
        raise ValueError("No messages to hand off")

    serialized = serialize_conversation(llm_messages)

    if cancel is not None and cancel.is_set():
        raise asyncio.CancelledError

    # Call LLM to extract context
    summary_text = await _extract_context(
        serialized=serialized,
        goal=goal,
        llm_client=llm_client,
        cancel=cancel,
    )

    # Collect file operations from entire raw history (not LLM view)
    all_raw_messages = collect_messages(history, 0, len(history))
    file_ops = collect_file_operations(
        session=session,
        summarized_messages=all_raw_messages,
        task_prefix_messages=[],
        previous_details=None,
    )
    file_ops_text = format_file_operations(file_ops.read_files, file_ops.modified_files)

    full_summary = f"{HANDOFF_SUMMARY_PREFIX}\n<summary>\n{summary_text}\n</summary>{file_ops_text}"

    # first_kept_index = len(history) means keep nothing from old history
    first_kept_index = len(history)
    kept_items_brief = collect_kept_items_brief(history, first_kept_index)

    return CompactionResult(
        summary=full_summary,
        first_kept_index=first_kept_index,
        tokens_before=tokens_before,
        details=file_ops,
        kept_items_brief=kept_items_brief,
    )


async def _extract_context(
    *,
    serialized: str,
    goal: str,
    llm_client: LLMClientABC,
    cancel: asyncio.Event | None,
) -> str:
    prompt_text = HANDOFF_EXTRACTION_PROMPT.format(goal=goal)
    input_messages: list[message.Message] = [
        message.UserMessage(
            parts=[
                message.TextPart(text=f"<conversation>\n{serialized}\n</conversation>"),
                message.TextPart(text=f"\n\n<instructions>\n{prompt_text}\n</instructions>"),
            ]
        )
    ]
    return await _call_extractor(
        input=input_messages,
        llm_client=llm_client,
        cancel=cancel,
    )


async def _call_extractor(
    *,
    input: list[message.Message],
    llm_client: LLMClientABC,
    cancel: asyncio.Event | None,
) -> str:
    if cancel is not None and cancel.is_set():
        raise asyncio.CancelledError

    for attempt in range(MAX_FAILED_TURN_RETRIES + 1):
        try:
            return await _call_extractor_once(
                input=input,
                llm_client=llm_client,
                cancel=cancel,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            if attempt >= MAX_FAILED_TURN_RETRIES:
                raise
            delay = _retry_delay_seconds(attempt + 1)
            if cancel is None:
                await asyncio.sleep(delay)
                continue
            try:
                await asyncio.wait_for(cancel.wait(), timeout=delay)
                raise asyncio.CancelledError
            except TimeoutError:
                continue

    raise RuntimeError("Extractor retry loop exited unexpectedly")


async def _call_extractor_once(
    *,
    input: list[message.Message],
    llm_client: LLMClientABC,
    cancel: asyncio.Event | None,
) -> str:
    if cancel is not None and cancel.is_set():
        raise asyncio.CancelledError

    call_param = llm_param.LLMCallParameter(
        input=input,
        system=HANDOFF_SYSTEM_PROMPT,
        session_id=None,
    )
    call_param.tools = None

    stream = await llm_client.call(call_param)
    accumulated: list[str] = []
    final_text: str | None = None
    async for item in stream:
        if isinstance(item, message.AssistantTextDelta):
            accumulated.append(item.content)
        elif isinstance(item, message.StreamErrorItem):
            raise RuntimeError(item.error)
        elif isinstance(item, message.AssistantMessage):
            final_text = message.join_text_parts(item.parts)

    if cancel is not None and cancel.is_set():
        raise asyncio.CancelledError

    text = final_text if final_text is not None else "".join(accumulated)
    if not text.strip():
        raise ValueError("Context extractor returned empty output")
    return text.strip()


def _retry_delay_seconds(attempt: int) -> float:
    capped_attempt = max(1, attempt)
    delay = INITIAL_RETRY_DELAY_S * (2 ** (capped_attempt - 1))
    return min(delay, MAX_RETRY_DELAY_S)
