"""Context-window usage analysis.

Produces a single ``ContextUsageUIExtra`` describing how the context window is spent, so the
TUI, the web UI, and any future non-interactive caller all read from one computation.

What is measured is the *LLM-facing* view (``session.get_llm_history()``), not the raw
conversation history, because compaction and rewind change what the model actually sees.

Memory and skill listings reach the model as ``DeveloperMessage`` items inside that history,
so they are carved out of it by their UI metadata rather than counted separately -- counting
them on their own would double-count them against "messages".
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from klaude_code.agent.attachments.memory import memory_attachment
from klaude_code.agent.attachments.skills import available_skills_attachment
from klaude_code.agent.token_estimate import IMAGE_TOKENS, MESSAGE_OVERHEAD_TOKENS, estimate_text_tokens
from klaude_code.const import DEFAULT_MAX_TOKENS
from klaude_code.log import log_debug
from klaude_code.protocol import llm_param, message
from klaude_code.protocol.models import (
    ContextCategory,
    ContextCategoryKey,
    ContextDetailEntry,
    ContextDetailSection,
    ContextUsageUIExtra,
    MemoryLoadedUIItem,
    SkillActivatedUIItem,
    SkillDiscoveredUIItem,
    SkillListingUIItem,
)
from klaude_code.session import Session

_CATEGORY_LABELS: dict[ContextCategoryKey, str] = {
    "system_prompt": "System prompt",
    "system_tools": "System tools",
    "memory": "Memory files",
    "skills": "Skills",
    "messages": "Messages",
    "autocompact_reserve": "Autocompact reserve",
    "free": "Free space",
}


@dataclass
class _Bucket:
    tokens: int = 0
    entries: list[ContextDetailEntry] = field(default_factory=lambda: [])

    def add(self, name: str, tokens: int) -> None:
        self.tokens += tokens
        self.entries.append(ContextDetailEntry(name=name, tokens=tokens))


def _estimate_message_tokens(msg: message.Message) -> int:
    """Estimate one message, including its structural overhead on the wire."""
    tokens = MESSAGE_OVERHEAD_TOKENS
    for part in msg.parts:
        if isinstance(part, (message.TextPart, message.ThinkingTextPart)):
            tokens += estimate_text_tokens(part.text)
        elif isinstance(part, message.ToolCallPart):
            tokens += estimate_text_tokens(part.tool_name) + estimate_text_tokens(part.arguments_json)
        elif isinstance(part, (message.ImageURLPart, message.ImageFilePart)):
            tokens += IMAGE_TOKENS
    if isinstance(msg, message.ToolResultMessage):
        tokens += estimate_text_tokens(msg.output_text)
    return tokens


def _estimate_tool_tokens(tool: llm_param.ToolSchema) -> int:
    """A tool costs its name, description, and the serialized JSON schema of its parameters."""
    schema_json = json.dumps(tool.parameters, separators=(",", ":"), ensure_ascii=False)
    return estimate_text_tokens(tool.name) + estimate_text_tokens(tool.description) + estimate_text_tokens(schema_json)


def _classify_developer_message(msg: message.DeveloperMessage) -> ContextCategoryKey:
    """Route a developer message to memory/skills, falling back to plain messages."""
    if msg.ui_extra is None:
        return "messages"
    for item in msg.ui_extra.items:
        if isinstance(item, MemoryLoadedUIItem):
            return "memory"
        if isinstance(item, (SkillListingUIItem, SkillActivatedUIItem, SkillDiscoveredUIItem)):
            return "skills"
    return "messages"


def _developer_message_names(msg: message.DeveloperMessage, category: ContextCategoryKey) -> list[str]:
    if msg.ui_extra is None:
        return []
    names: list[str] = []
    for item in msg.ui_extra.items:
        if category == "memory" and isinstance(item, MemoryLoadedUIItem):
            names.extend(entry.path for entry in item.files)
        elif category == "skills":
            if isinstance(item, SkillListingUIItem):
                names.extend(item.names)
            elif isinstance(item, (SkillActivatedUIItem, SkillDiscoveredUIItem)):
                names.append(item.name)
    return names


def _entry_weights(text: str, names: list[str], category: ContextCategoryKey) -> list[int]:
    """Weight each named item by the size of its own slice of the block's text.

    Splitting the block evenly would report every memory file and every skill at the same
    cost, which hides exactly what this command exists to surface. Both formats are
    locatable: a memory file opens with ``Contents of <path> (``, and a skill occupies one
    ``<skill name="...">`` line. Anything unmatched falls back to an even share.
    """
    weights: list[int] = []
    if category == "memory":
        # Slice from each file's header to the start of the next one.
        offsets: list[tuple[int, str]] = []
        for name in names:
            position = text.find(f"Contents of {name} (")
            offsets.append((position if position >= 0 else len(text), name))
        ordered = sorted(range(len(names)), key=lambda index: offsets[index][0])
        slice_tokens: dict[int, int] = {}
        for rank, index in enumerate(ordered):
            start = offsets[index][0]
            end = offsets[ordered[rank + 1]][0] if rank + 1 < len(ordered) else len(text)
            slice_tokens[index] = estimate_text_tokens(text[start:end]) if start < end else 0
        weights = [slice_tokens.get(index, 0) for index in range(len(names))]
    else:
        by_name: dict[str, int] = {}
        for line in text.splitlines():
            if 'name="' not in line:
                continue
            start = line.index('name="') + len('name="')
            end = line.find('"', start)
            if end > start:
                by_name[line[start:end]] = estimate_text_tokens(line)
        weights = [by_name.get(name, 0) for name in names]

    if sum(weights) <= 0:
        return [1] * len(names)
    # A name we could not locate still deserves a nominal share rather than zero.
    return [weight or 1 for weight in weights]


def _distribute(total: int, weights: list[int]) -> list[int]:
    """Split ``total`` across ``weights`` proportionally, preserving the exact sum."""
    weight_sum = sum(weights)
    if weight_sum <= 0:
        return [0] * len(weights)
    exact = [total * weight / weight_sum for weight in weights]
    allocated = [int(value) for value in exact]
    for index in sorted(range(len(exact)), key=lambda i: -(exact[i] - int(exact[i]))):
        if sum(allocated) >= total:
            break
        allocated[index] += 1
    return allocated


def _add_named_entries(
    bucket: _Bucket, msg: message.DeveloperMessage, category: ContextCategoryKey, tokens: int
) -> None:
    """Attribute a block's cost to the items it announced, weighted by their own text."""
    names = _developer_message_names(msg, category)
    if not names:
        bucket.tokens += tokens
        return
    text = message.join_text_parts(msg.parts)
    for name, share in zip(names, _distribute(tokens, _entry_weights(text, names, category)), strict=True):
        bucket.add(name, share)


def _last_real_usage(session: Session) -> tuple[int, int] | None:
    """Return ``(history_index, context_size)`` for the newest successful API usage report."""
    history = session.conversation_history
    for index in range(len(history) - 1, -1, -1):
        item = history[index]
        if not isinstance(item, message.AssistantMessage):
            continue
        if item.usage is None or item.stop_reason in {"aborted", "error"}:
            continue
        context_size = item.usage.context_size or item.usage.total_tokens
        if context_size:
            return index, context_size
    return None


def _split_history_tokens(
    history: list[message.HistoryEvent],
) -> tuple[dict[ContextCategoryKey, _Bucket], int]:
    """Split the LLM-facing history into memory / skills / messages buckets."""
    buckets: dict[ContextCategoryKey, _Bucket] = {
        "memory": _Bucket(),
        "skills": _Bucket(),
        "messages": _Bucket(),
    }
    message_count = 0

    for item in history:
        if not isinstance(item, message.Message):
            continue
        message_count += 1
        tokens = _estimate_message_tokens(item)

        if isinstance(item, message.DeveloperMessage):
            category = _classify_developer_message(item)
            if category == "messages":
                buckets["messages"].tokens += tokens
            else:
                _add_named_entries(buckets[category], item, category, tokens)
            continue

        buckets["messages"].tokens += tokens

    return buckets, message_count


def _autocompact_reserve(llm_config: llm_param.LLMConfigParameter, context_limit: int) -> int:
    """Tokens held back from the usable window: model output plus the compaction reserve."""
    if context_limit <= 0:
        return 0
    max_tokens = llm_config.max_tokens or DEFAULT_MAX_TOKENS
    compaction_reserve = min(16384, max(2048, int(context_limit * 0.25)))
    return min(context_limit, max_tokens + compaction_reserve)


def _preview_sandbox(session: Session) -> Session:
    """A throwaway session standing in for the real one while previewing attachments.

    These attachments record what they inject in ``file_tracker``, so they must not run
    against the live session -- doing so would make the next real turn skip the blocks. A
    full ``model_copy(deep=True)`` is not an option (the session holds an unpicklable store
    handle), so only the state the attachments actually touch is carried over: ``work_dir``
    and the history they read, plus a copied ``file_tracker`` to absorb their writes.
    """
    return Session(
        work_dir=session.work_dir,
        conversation_history=list(session.conversation_history),
        file_tracker=dict(session.file_tracker),
    )


async def _preview_pending_attachments(session: Session) -> dict[ContextCategoryKey, _Bucket]:
    """Measure memory/skill blocks that the next request will prepend but history lacks.

    Calling the real attachment functions (rather than re-deriving the text) keeps the
    preview identical to what gets sent. Anything already present in history returns ``None``
    here, so nothing is double-counted.
    """
    buckets: dict[ContextCategoryKey, _Bucket] = {"memory": _Bucket(), "skills": _Bucket()}
    try:
        sandbox = _preview_sandbox(session)
        pending = [
            await memory_attachment(sandbox),
            await available_skills_attachment(sandbox),
        ]
    except Exception as exc:
        # Usage reporting must never break the session it is reporting on.
        log_debug(f"context_usage: pending attachment preview failed: {exc!r}")
        return buckets

    for item in pending:
        if item is None:
            continue
        category = _classify_developer_message(item)
        if category not in buckets:
            continue
        _add_named_entries(buckets[category], item, category, _estimate_message_tokens(item))
    return buckets


async def analyze_context_usage(
    *,
    session: Session,
    system_prompt: str | None,
    tools: list[llm_param.ToolSchema],
    llm_config: llm_param.LLMConfigParameter,
    model_name: str,
) -> ContextUsageUIExtra:
    """Estimate how the context window is currently spent."""

    history = session.get_llm_history()
    buckets, _ = _split_history_tokens(history)

    # On a fresh session the memory and skill blocks have not been injected yet; report what
    # the next request will carry instead of showing zero.
    for category, pending in (await _preview_pending_attachments(session)).items():
        buckets[category].tokens += pending.tokens
        buckets[category].entries.extend(pending.entries)

    system_prompt_tokens = estimate_text_tokens(system_prompt or "")
    tool_bucket = _Bucket()
    for tool in sorted(tools, key=lambda schema: schema.name):
        tool_bucket.add(tool.name, _estimate_tool_tokens(tool))

    raw_tokens: dict[ContextCategoryKey, int] = {
        "system_prompt": system_prompt_tokens,
        "system_tools": tool_bucket.tokens,
        "memory": buckets["memory"].tokens,
        "skills": buckets["skills"].tokens,
        "messages": buckets["messages"].tokens,
    }

    # Calibrate against real usage when we can compare like with like: estimate the same
    # prefix the last successful response saw, and scale by how far off we were.
    scale = 1.0
    is_calibrated = False
    real_usage = _last_real_usage(session)
    if real_usage is not None:
        usage_index, real_context_size = real_usage
        prefix_buckets, _ = _split_history_tokens(session.get_llm_history(until_index=usage_index + 1))
        estimated_prefix = (
            system_prompt_tokens + tool_bucket.tokens + sum(bucket.tokens for bucket in prefix_buckets.values())
        )
        if estimated_prefix > 0:
            scale = real_context_size / estimated_prefix
            is_calibrated = True

    def scaled(value: int) -> int:
        return round(value * scale)

    context_limit = llm_config.context_limit or 0
    used_tokens = sum(scaled(value) for value in raw_tokens.values())

    categories = [
        ContextCategory(key=key, label=_CATEGORY_LABELS[key], tokens=scaled(value)) for key, value in raw_tokens.items()
    ]

    reserve = _autocompact_reserve(llm_config, context_limit)
    if reserve:
        categories.append(
            ContextCategory(
                key="autocompact_reserve",
                label=_CATEGORY_LABELS["autocompact_reserve"],
                tokens=min(reserve, max(0, context_limit - used_tokens)),
            )
        )
    if context_limit > 0:
        accounted = sum(category.tokens for category in categories)
        categories.append(
            ContextCategory(
                key="free",
                label=_CATEGORY_LABELS["free"],
                tokens=max(0, context_limit - accounted),
            )
        )

    details: list[ContextDetailSection] = []
    detail_sources: tuple[tuple[ContextCategoryKey, _Bucket, str], ...] = (
        ("system_tools", tool_bucket, "tool"),
        ("memory", buckets["memory"], "file"),
        ("skills", buckets["skills"], "skill"),
    )
    for key, bucket, hint in detail_sources:
        if not bucket.entries:
            continue
        details.append(
            ContextDetailSection(
                key=key,
                label=_CATEGORY_LABELS[key],
                hint=hint,
                entries=[
                    ContextDetailEntry(name=entry.name, tokens=scaled(entry.tokens))
                    for entry in sorted(bucket.entries, key=lambda item: -item.tokens)
                ],
            )
        )

    return ContextUsageUIExtra(
        model_name=model_name,
        model_id=llm_config.model_id or model_name,
        used_tokens=used_tokens,
        context_limit=context_limit,
        categories=categories,
        details=details,
        is_calibrated=is_calibrated,
    )
