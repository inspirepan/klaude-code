from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from typing import cast

from klaude_code.llm import LLMClientABC
from klaude_code.protocol import llm_param, message, model
from klaude_code.session.session import Session

from .prompts import (
    COMPACTION_SUMMARY_PREFIX,
    SUMMARIZATION_PROMPT,
    SUMMARIZATION_SYSTEM_PROMPT,
    TASK_PREFIX_SUMMARIZATION_PROMPT,
    UPDATE_SUMMARIZATION_PROMPT,
)

_MAX_TOOL_OUTPUT_CHARS = 4000
_MAX_TOOL_CALL_CHARS = 2000
_DEFAULT_IMAGE_TOKENS = 1200


class CompactionReason(str, Enum):
    THRESHOLD = "threshold"
    OVERFLOW = "overflow"
    MANUAL = "manual"


@dataclass(frozen=True)
class CompactionConfig:
    reserve_tokens: int
    keep_recent_tokens: int
    max_summary_tokens: int


@dataclass(frozen=True)
class CompactionResult:
    summary: str
    first_kept_index: int
    tokens_before: int | None
    details: message.CompactionDetails | None
    kept_items_brief: list[message.KeptItemBrief]

    def to_entry(self) -> message.CompactionEntry:
        """Convert to a CompactionEntry for persisting in session history."""
        return message.CompactionEntry(
            summary=self.summary,
            first_kept_index=self.first_kept_index,
            tokens_before=self.tokens_before,
            details=self.details,
            kept_items_brief=self.kept_items_brief,
        )


def _resolve_compaction_config(llm_config: llm_param.LLMConfigParameter) -> CompactionConfig:
    default_reserve = 16384
    default_keep = 20000
    context_limit = llm_config.context_limit or 0
    if context_limit <= 0:
        reserve = default_reserve
        keep_recent = default_keep
    else:
        reserve = min(default_reserve, max(2048, int(context_limit * 0.25)))
        keep_recent = min(default_keep, max(4096, int(context_limit * 0.35)))
        max_keep = max(0, context_limit - reserve)
        if max_keep:
            keep_recent = min(keep_recent, max_keep)
    max_summary = max(1024, int(reserve * 0.8))
    return CompactionConfig(reserve_tokens=reserve, keep_recent_tokens=keep_recent, max_summary_tokens=max_summary)


def should_compact_threshold(
    *,
    session: Session,
    config: CompactionConfig | None,
    llm_config: llm_param.LLMConfigParameter,
) -> bool:
    compaction_config = config or _resolve_compaction_config(llm_config)
    context_limit = llm_config.context_limit or _get_last_context_limit(session)
    if context_limit is None:
        return False
    tokens_before = _get_last_context_tokens(session)
    # After compaction, the last successful assistant usage reflects the pre-compaction
    # context window. For threshold checks we want the *current* LLM-facing view.
    if tokens_before is None or _has_compaction_after_last_successful_usage(session):
        tokens_before = _estimate_history_tokens(session.get_llm_history())
    return tokens_before > context_limit - compaction_config.reserve_tokens


def _has_compaction_after_last_successful_usage(session: Session) -> bool:
    """Return True if the newest compaction entry is newer than the last usable assistant usage.

    In that case, usage.context_size is stale for threshold decisions.
    """

    history = session.conversation_history

    last_compaction_idx = -1
    for idx in range(len(history) - 1, -1, -1):
        if isinstance(history[idx], message.CompactionEntry):
            last_compaction_idx = idx
            break

    if last_compaction_idx < 0:
        return False

    last_usage_idx = -1
    for idx in range(len(history) - 1, -1, -1):
        item = history[idx]
        if not isinstance(item, message.AssistantMessage):
            continue
        if item.usage is None:
            continue
        if item.stop_reason in {"aborted", "error"}:
            continue
        last_usage_idx = idx
        break

    if last_usage_idx < 0:
        return True

    return last_compaction_idx > last_usage_idx


async def run_compaction(
    *,
    session: Session,
    reason: CompactionReason,
    focus: str | None,
    llm_client: LLMClientABC,
    llm_config: llm_param.LLMConfigParameter,
    cancel: asyncio.Event | None = None,
) -> CompactionResult:
    del reason
    if cancel is not None and cancel.is_set():
        raise asyncio.CancelledError

    compaction_config = _resolve_compaction_config(llm_config)
    history = session.conversation_history
    if not history:
        raise ValueError("No conversation history to compact")
    _, last_compaction = _find_last_compaction(history)
    base_start_index = last_compaction.first_kept_index if last_compaction else 0

    cut_index = _find_cut_index(history, base_start_index, compaction_config.keep_recent_tokens)
    cut_index = _adjust_cut_index(history, cut_index, base_start_index)

    if cut_index <= base_start_index:
        raise ValueError("Nothing to compact (session too small)")

    previous_summary = last_compaction.summary if last_compaction else None
    tokens_before = _get_last_context_tokens(session)
    if tokens_before is None:
        tokens_before = _estimate_history_tokens(history)

    split_task = _is_split_task(history, base_start_index, cut_index)
    task_start_index = _find_task_start_index(history, base_start_index, cut_index) if split_task else -1

    messages_to_summarize = _collect_messages(history, base_start_index, task_start_index if split_task else cut_index)
    task_prefix_messages: list[message.Message] = []
    if split_task and task_start_index >= 0:
        task_prefix_messages = _collect_messages(history, task_start_index, cut_index)

    if not messages_to_summarize and not task_prefix_messages and not previous_summary:
        raise ValueError("Nothing to compact (no messages to summarize)")

    if cancel is not None and cancel.is_set():
        raise asyncio.CancelledError

    summary = await _build_summary(
        messages_to_summarize=messages_to_summarize,
        task_prefix_messages=task_prefix_messages,
        previous_summary=previous_summary,
        focus=focus,
        llm_client=llm_client,
        config=compaction_config,
        cancel=cancel,
    )

    file_ops = _collect_file_operations(
        session=session,
        summarized_messages=messages_to_summarize,
        task_prefix_messages=task_prefix_messages,
        previous_details=last_compaction.details if last_compaction else None,
    )
    summary += _format_file_operations(file_ops.read_files, file_ops.modified_files)

    kept_items_brief = _collect_kept_items_brief(history, cut_index)

    return CompactionResult(
        summary=summary,
        first_kept_index=cut_index,
        tokens_before=tokens_before,
        details=file_ops,
        kept_items_brief=kept_items_brief,
    )


def _collect_kept_items_brief(history: list[message.HistoryEvent], cut_index: int) -> list[message.KeptItemBrief]:
    """Extract brief info about kept (non-compacted) messages."""
    items: list[message.KeptItemBrief] = []
    tool_counts: dict[str, int] = {}

    def _flush_tool_counts() -> None:
        for tool_name, count in tool_counts.items():
            items.append(message.KeptItemBrief(item_type=tool_name, count=count))
        tool_counts.clear()

    def _get_preview(text: str, max_len: int = 30) -> str:
        text = text.strip().replace("\n", " ")
        if len(text) > max_len:
            return text[:max_len] + "..."
        return text

    for idx in range(cut_index, len(history)):
        item = history[idx]
        if isinstance(item, message.CompactionEntry):
            continue

        if isinstance(item, message.UserMessage):
            _flush_tool_counts()
            text = _join_text_parts(item.parts)
            items.append(message.KeptItemBrief(item_type="User", preview=_get_preview(text)))

        elif isinstance(item, message.AssistantMessage):
            _flush_tool_counts()
            text = _join_text_parts(item.parts)
            if text.strip():
                items.append(message.KeptItemBrief(item_type="Assistant", preview=_get_preview(text)))

        elif isinstance(item, message.ToolResultMessage):
            tool_name = _normalize_tool_name(str(item.tool_name))
            tool_counts[tool_name] = tool_counts.get(tool_name, 0) + 1

    _flush_tool_counts()
    return items


def _normalize_tool_name(tool_name: str) -> str:
    """Return tool name as-is (no normalization).

    We intentionally avoid enumerating tool names here; display should reflect
    what was recorded in history.
    """

    return tool_name.strip()


def _call_args_probably_modify_file(args: dict[str, object]) -> bool:
    """Heuristically detect file modifications from tool call arguments.

    This avoids enumerating tool names; we infer intent from argument structure.
    """

    # Common edit signature.
    if "old" in args and "new" in args:
        return True
    # Common write signature.
    if "content" in args:
        return True
    # Common apply_patch signature.
    patch = args.get("patch")
    if isinstance(patch, str) and "*** Begin Patch" in patch:
        return True
    # Batch edits.
    edits = args.get("edits")
    return bool(isinstance(edits, list))


def _collect_file_operations(
    *,
    session: Session,
    summarized_messages: list[message.Message],
    task_prefix_messages: list[message.Message],
    previous_details: message.CompactionDetails | None,
) -> message.CompactionDetails:
    read_set: set[str] = set()
    modified_set: set[str] = set()

    if previous_details is not None:
        read_set.update(previous_details.read_files)
        modified_set.update(previous_details.modified_files)

    for path in session.file_tracker:
        read_set.add(path)

    for msg in (*summarized_messages, *task_prefix_messages):
        if isinstance(msg, message.AssistantMessage):
            _extract_file_ops_from_tool_calls(msg, read_set, modified_set)
        if isinstance(msg, message.ToolResultMessage):
            _extract_modified_files_from_tool_result(msg, modified_set)

    read_files = sorted(read_set - modified_set)
    modified_files = sorted(modified_set)
    return message.CompactionDetails(read_files=read_files, modified_files=modified_files)


def _extract_file_ops_from_tool_calls(
    msg: message.AssistantMessage, read_set: set[str], modified_set: set[str]
) -> None:
    for part in msg.parts:
        if not isinstance(part, message.ToolCallPart):
            continue
        try:
            args = json.loads(part.arguments_json)
        except json.JSONDecodeError:
            continue
        if not isinstance(args, dict):
            continue
        args_dict = cast(dict[str, object], args)
        path = args_dict.get("file_path") or args_dict.get("path")
        if not isinstance(path, str):
            continue

        # Always track referenced paths as read context.
        read_set.add(path)

        # Detect modifications via argument structure (no tool name enumeration).
        if _call_args_probably_modify_file(args_dict):
            modified_set.add(path)


def _extract_modified_files_from_tool_result(msg: message.ToolResultMessage, modified_set: set[str]) -> None:
    ui_extra = msg.ui_extra
    if ui_extra is None:
        return
    match ui_extra:
        case model.DiffUIExtra() as diff:
            modified_set.update(file.file_path for file in diff.files)
        case model.MarkdownDocUIExtra() as doc:
            modified_set.add(doc.file_path)
        case model.MultiUIExtra() as multi:
            for item in multi.items:
                if isinstance(item, model.DiffUIExtra):
                    modified_set.update(file.file_path for file in item.files)
                elif isinstance(item, model.MarkdownDocUIExtra):
                    modified_set.add(item.file_path)
        case _:
            pass


def _format_file_operations(read_files: list[str], modified_files: list[str]) -> str:
    sections: list[str] = []
    if read_files:
        sections.append("<read-files>\n" + "\n".join(read_files) + "\n</read-files>")
    if modified_files:
        sections.append("<modified-files>\n" + "\n".join(modified_files) + "\n</modified-files>")
    if not sections:
        return ""
    return "\n\n" + "\n\n".join(sections)


def _find_last_compaction(
    history: list[message.HistoryEvent],
) -> tuple[int, message.CompactionEntry | None]:
    for idx in range(len(history) - 1, -1, -1):
        item = history[idx]
        if isinstance(item, message.CompactionEntry):
            return idx, item
    return -1, None


def _find_cut_index(history: list[message.HistoryEvent], start_index: int, keep_recent_tokens: int) -> int:
    tokens = 0
    cut_index = start_index
    for idx in range(len(history) - 1, start_index - 1, -1):
        item = history[idx]
        if isinstance(item, message.CompactionEntry):
            continue
        if isinstance(item, message.Message):
            tokens += _estimate_tokens(item)
        # Never cut on a tool result; keeping tool results without their corresponding
        # assistant tool call breaks LLM-facing history.
        if (
            tokens >= keep_recent_tokens
            and isinstance(item, message.Message)
            and not isinstance(item, message.ToolResultMessage)
        ):
            cut_index = idx
            break
    return cut_index


def _adjust_cut_index(history: list[message.HistoryEvent], cut_index: int, start_index: int) -> int:
    if not history:
        return 0
    if cut_index < start_index:
        return start_index

    def _skip_leading_tool_results(idx: int) -> int:
        while idx < len(history) and isinstance(history[idx], message.ToolResultMessage):
            idx += 1
        return idx

    # Prefer moving the cut backwards to include the assistant tool call.
    while cut_index > start_index and isinstance(history[cut_index], message.ToolResultMessage):
        cut_index -= 1

    # If we cannot move backwards enough (e.g. start_index is itself a tool result due to
    # old persisted sessions), move forward to avoid starting kept history with tool results.
    if isinstance(history[cut_index], message.ToolResultMessage):
        forward = _skip_leading_tool_results(cut_index)
        if forward < len(history):
            cut_index = forward

    if isinstance(history[cut_index], message.DeveloperMessage):
        forward = _find_anchor_index(history, cut_index + 1, forward=True)
        if forward is not None:
            return forward
        backward = _find_anchor_index(history, cut_index - 1, forward=False)
        if backward is not None:
            return backward

    return cut_index


def _find_anchor_index(history: list[message.HistoryEvent], start: int, *, forward: bool) -> int | None:
    indices = range(start, len(history)) if forward else range(start, -1, -1)
    for idx in indices:
        item = history[idx]
        if isinstance(item, (message.UserMessage, message.ToolResultMessage)):
            return idx
    return None


def _is_split_task(history: list[message.HistoryEvent], start_index: int, cut_index: int) -> bool:
    if cut_index <= start_index:
        return False
    if isinstance(history[cut_index], message.UserMessage):
        return False
    task_start_index = _find_task_start_index(history, start_index, cut_index)
    return task_start_index >= 0


def _find_task_start_index(history: list[message.HistoryEvent], start_index: int, cut_index: int) -> int:
    for idx in range(cut_index, start_index - 1, -1):
        if isinstance(history[idx], message.UserMessage):
            return idx
    return -1


def _collect_messages(history: list[message.HistoryEvent], start_index: int, end_index: int) -> list[message.Message]:
    if end_index < start_index:
        return []
    return [
        item
        for item in history[start_index:end_index]
        if isinstance(item, message.Message) and not isinstance(item, message.SystemMessage)
    ]


async def _build_summary(
    *,
    messages_to_summarize: list[message.Message],
    task_prefix_messages: list[message.Message],
    previous_summary: str | None,
    focus: str | None,
    llm_client: LLMClientABC,
    config: CompactionConfig,
    cancel: asyncio.Event | None,
) -> str:
    if cancel is not None and cancel.is_set():
        raise asyncio.CancelledError

    if task_prefix_messages:
        history_task = (
            _generate_summary(
                messages_to_summarize,
                llm_client,
                config,
                focus,
                previous_summary,
                cancel,
            )
            if messages_to_summarize
            else asyncio.sleep(0, result=previous_summary or "")
        )
        prefix_task = _generate_task_prefix_summary(task_prefix_messages, llm_client, config, cancel)
        history_summary, task_prefix_summary = await asyncio.gather(history_task, prefix_task)
        return f"{COMPACTION_SUMMARY_PREFIX}\n\n<summary>{history_summary}\n\n---\n\n**Task Context (current task):**\n\n{task_prefix_summary}\n\n</summary>"

    return await _generate_summary(
        messages_to_summarize,
        llm_client,
        config,
        focus,
        previous_summary,
        cancel,
    )


async def _generate_summary(
    messages_to_summarize: list[message.Message],
    llm_client: LLMClientABC,
    config: CompactionConfig,
    focus: str | None,
    previous_summary: str | None,
    cancel: asyncio.Event | None,
) -> str:
    serialized = _serialize_conversation(messages_to_summarize)
    parts: list[message.Part] = [
        message.TextPart(text=f"<conversation>\n{serialized}\n</conversation>"),
    ]
    if previous_summary:
        parts.append(
            message.TextPart(text=f"\n\n<previous-summary>\n{previous_summary}\n</previous-summary>"),
        )
        base_prompt = UPDATE_SUMMARIZATION_PROMPT
    else:
        base_prompt = SUMMARIZATION_PROMPT
    parts.append(
        message.TextPart(text=f"\n\n<instructions>\n{base_prompt}\n</instructions>"),
    )
    if focus:
        parts.append(
            message.TextPart(text=f"\n\nAdditional focus: {focus}"),
        )
    return await _call_summarizer(
        input=[message.UserMessage(parts=parts)],
        llm_client=llm_client,
        max_tokens=config.max_summary_tokens,
        cancel=cancel,
    )


async def _generate_task_prefix_summary(
    messages: list[message.Message],
    llm_client: LLMClientABC,
    config: CompactionConfig,
    cancel: asyncio.Event | None,
) -> str:
    serialized = _serialize_conversation(messages)
    return await _call_summarizer(
        input=[
            message.UserMessage(
                parts=[
                    message.TextPart(text=f"<conversation>\n{serialized}\n</conversation>\n\n"),
                    message.TextPart(text=TASK_PREFIX_SUMMARIZATION_PROMPT),
                ]
            )
        ],
        llm_client=llm_client,
        max_tokens=config.max_summary_tokens,
        cancel=cancel,
    )


async def _call_summarizer(
    *,
    input: list[message.Message],
    llm_client: LLMClientABC,
    max_tokens: int,
    cancel: asyncio.Event | None,
) -> str:
    if cancel is not None and cancel.is_set():
        raise asyncio.CancelledError

    call_param = llm_param.LLMCallParameter(
        input=input,
        system=SUMMARIZATION_SYSTEM_PROMPT,
        session_id=None,
    )
    call_param.max_tokens = max_tokens
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
        raise ValueError("Summarizer returned empty output")
    return text.strip()


def _serialize_conversation(messages: list[message.Message]) -> str:
    parts: list[str] = []
    for msg in messages:
        if isinstance(msg, message.UserMessage):
            text = _join_text_parts(msg.parts)
            if not text:
                text = _render_images(msg.parts)
            if text:
                parts.append(f"[User]: {text}")
        elif isinstance(msg, message.AssistantMessage):
            text_parts: list[str] = []
            thinking_parts: list[str] = []
            tool_calls: list[str] = []
            for part in msg.parts:
                if isinstance(part, message.TextPart):
                    text_parts.append(part.text)
                elif isinstance(part, message.ThinkingTextPart):
                    thinking_parts.append(part.text)
                elif isinstance(part, message.ToolCallPart):
                    args = _truncate_text(part.arguments_json, _MAX_TOOL_CALL_CHARS)
                    tool_calls.append(f"{part.tool_name}({args})")
            if thinking_parts:
                parts.append("[Assistant thinking]: " + "\n".join(thinking_parts))
            if text_parts:
                parts.append("[Assistant]: " + "\n".join(text_parts))
            if tool_calls:
                parts.append("[Assistant tool calls]: " + "; ".join(tool_calls))
        elif isinstance(msg, message.ToolResultMessage):
            content = _truncate_text(msg.output_text, _MAX_TOOL_OUTPUT_CHARS)
            if content:
                parts.append(f"[Tool result]: {content}")
        elif isinstance(msg, message.DeveloperMessage):
            text = _join_text_parts(msg.parts)
            if text:
                parts.append(f"[Developer]: {text}")
        else:  # SystemMessage
            text = _join_text_parts(msg.parts)
            if text:
                parts.append(f"[System]: {text}")
    return "\n\n".join(parts)


def _join_text_parts(parts: Sequence[message.Part]) -> str:
    return "".join(part.text for part in parts if isinstance(part, message.TextPart))


def _render_images(parts: Sequence[message.Part]) -> str:
    images: list[str] = []
    for part in parts:
        if isinstance(part, message.ImageURLPart):
            images.append(part.url)
        elif isinstance(part, message.ImageFilePart):
            images.append(part.file_path)
    if not images:
        return ""
    return "image: " + ", ".join(images)


def _truncate_text(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "...(truncated)"


def _estimate_history_tokens(history: list[message.HistoryEvent]) -> int:
    return sum(_estimate_tokens(item) for item in history if isinstance(item, message.Message))


def _estimate_tokens(msg: message.Message) -> int:
    chars = 0
    if isinstance(msg, message.UserMessage):
        chars = sum(len(part.text) for part in msg.parts if isinstance(part, message.TextPart))
        chars += _count_image_tokens(msg.parts)
    elif isinstance(msg, message.AssistantMessage):
        for part in msg.parts:
            if isinstance(part, (message.TextPart, message.ThinkingTextPart)):
                chars += len(part.text)
            elif isinstance(part, message.ToolCallPart):
                chars += len(part.tool_name) + len(part.arguments_json)
    elif isinstance(msg, message.ToolResultMessage):
        chars += len(msg.output_text)
        chars += _count_image_tokens(msg.parts)
    else:  # DeveloperMessage or SystemMessage
        chars += sum(len(part.text) for part in msg.parts if isinstance(part, message.TextPart))
    return max(1, (chars + 3) // 4)


def _count_image_tokens(parts: list[message.Part]) -> int:
    count = sum(1 for part in parts if isinstance(part, (message.ImageURLPart, message.ImageFilePart)))
    return count * _DEFAULT_IMAGE_TOKENS


def _get_last_context_tokens(session: Session) -> int | None:
    for item in reversed(session.conversation_history):
        if not isinstance(item, message.AssistantMessage):
            continue
        if item.usage is None:
            continue
        if item.stop_reason in {"aborted", "error"}:
            continue
        usage = item.usage
        if usage.context_size is not None:
            return usage.context_size
        return usage.total_tokens
    return None


def _get_last_context_limit(session: Session) -> int | None:
    for item in reversed(session.conversation_history):
        if not isinstance(item, message.AssistantMessage):
            continue
        if item.usage is None:
            continue
        if item.usage.context_limit is not None:
            return item.usage.context_limit
    return None
