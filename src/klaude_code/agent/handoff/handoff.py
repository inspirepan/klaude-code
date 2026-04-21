from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from klaude_code.agent.agent_profile import AgentProfile
from klaude_code.agent.cache_safe import (
    CacheSafeParams,
    build_cache_safe_messages,
    build_fork_cache_event,
    is_cache_sharable,
)
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
from klaude_code.prompts.handoff import (
    HANDOFF_EXTRACTION_PROMPT,
    HANDOFF_FORK_PROMPT,
    HANDOFF_SUMMARY_PREFIX,
    HANDOFF_SYSTEM_PROMPT,
)
from klaude_code.protocol import llm_param, message
from klaude_code.protocol.models import Usage

if TYPE_CHECKING:
    from klaude_code.session.session import Session


async def run_handoff(
    *,
    session: Session,
    goal: str,
    llm_client: LLMClientABC,
    llm_config: llm_param.LLMConfigParameter,
    cancel: asyncio.Event | None = None,
    main_profile: AgentProfile | None = None,
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

    use_fork = main_profile is not None and is_cache_sharable(main_profile, llm_client)

    if use_fork:
        assert main_profile is not None
        summary_text, fork_usage = await _build_handoff_fork(
            session=session,
            main_profile=main_profile,
            goal=goal,
            cancel=cancel,
        )
    else:
        # Use LLM-facing history (includes compaction summary) rather than raw history,
        # so previously compacted context is not lost.
        llm_history = session.get_llm_history()
        llm_messages = [item for item in llm_history if isinstance(item, message.Message)]
        if not llm_messages:
            raise ValueError("No messages to hand off")

        serialized = serialize_conversation(llm_messages)

        if cancel is not None and cancel.is_set():
            raise asyncio.CancelledError

        summary_text = await _extract_context(
            serialized=serialized,
            goal=goal,
            llm_client=llm_client,
            cancel=cancel,
        )
        fork_usage = None

    # Collect file operations from entire raw history (not LLM view)
    all_raw_messages = collect_messages(history, 0, len(history))
    file_ops = collect_file_operations(
        session=session,
        summarized_messages=all_raw_messages,
        task_prefix_messages=[],
        previous_details=None,
    )
    file_ops_text = format_file_operations(file_ops.read_files, file_ops.modified_files)

    full_summary = (
        f"{HANDOFF_SUMMARY_PREFIX}\n"
        f"<original-handoff-goal>\n{goal}\n</original-handoff-goal>\n"
        f"<summary>\n{summary_text}\n</summary>{file_ops_text}"
    )

    # first_kept_index = len(history) means keep nothing from old history
    first_kept_index = len(history)
    kept_items_brief = collect_kept_items_brief(history, first_kept_index)

    fork_event = build_fork_cache_event(
        session_id=session.id,
        fork_label="handoff",
        usage=fork_usage,
        fallback_used=not use_fork,
    )

    return CompactionResult(
        summary=full_summary,
        first_kept_index=first_kept_index,
        tokens_before=tokens_before,
        details=file_ops,
        kept_items_brief=kept_items_brief,
        fork_event=fork_event,
    )


async def _build_handoff_fork(
    *,
    session: Session,
    main_profile: AgentProfile,
    goal: str,
    cancel: asyncio.Event | None,
) -> tuple[str, Usage | None]:
    """Build a handoff summary by asking the main LLM to stop and summarize in-line.

    Wire prefix matches the parent's last request (via ``session.get_llm_history()``),
    so the server-side prompt cache is reused. Only the appended handoff request
    (and the response) is paid as fresh tokens.
    """
    if cancel is not None and cancel.is_set():
        raise asyncio.CancelledError

    prefix_messages = session.get_llm_history()
    prompt_text = HANDOFF_FORK_PROMPT.format(goal=goal)
    extra: list[message.HistoryEvent] = [message.UserMessage(parts=[message.TextPart(text=prompt_text)])]
    cache_safe = CacheSafeParams(profile=main_profile, prefix_messages=prefix_messages)
    wire_messages = build_cache_safe_messages(cache_safe, extra)
    input_messages = [m for m in wire_messages if isinstance(m, message.Message)]

    call_param = llm_param.LLMCallParameter(
        input=input_messages,
        system=main_profile.system_prompt,
        session_id=None,
    )
    call_param.tools = main_profile.tools  # Must match parent; tools=[] would break cache.

    stream = await main_profile.llm_client.call(call_param)
    accumulated: list[str] = []
    final_message: message.AssistantMessage | None = None
    async for item in stream:
        if isinstance(item, message.AssistantTextDelta):
            accumulated.append(item.content)
        elif isinstance(item, message.StreamErrorItem):
            raise RuntimeError(item.error)
        elif isinstance(item, message.AssistantMessage):
            final_message = item

    if cancel is not None and cancel.is_set():
        raise asyncio.CancelledError

    text = message.join_text_parts(final_message.parts) if final_message else "".join(accumulated)
    if not text.strip():
        raise ValueError("Handoff extractor returned empty output")
    usage = final_message.usage if final_message else None
    return text.strip(), usage


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
