"""Common utilities for converting conversation history to LLM input formats.

This module provides shared abstractions for providers that require message grouping
(Anthropic, OpenAI-compatible, OpenRouter). The Responses API doesn't need this
since it uses a flat item list matching our internal protocol.
"""

from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

from klaude_code import const

if TYPE_CHECKING:
    from klaude_code.protocol.llm_param import LLMCallParameter, LLMConfigParameter

from klaude_code.protocol import model


class GroupKind(Enum):
    ASSISTANT = "assistant"
    USER = "user"
    TOOL = "tool"
    DEVELOPER = "developer"
    OTHER = "other"


@dataclass
class UserGroup:
    """Aggregated user message group (UserMessageItem + DeveloperMessageItem)."""

    text_parts: list[str] = field(default_factory=lambda: [])
    images: list[model.ImageURLPart] = field(default_factory=lambda: [])


@dataclass
class ToolGroup:
    """Aggregated tool result group (ToolResultItem + trailing DeveloperMessageItems)."""

    tool_result: model.ToolResultItem
    reminder_texts: list[str] = field(default_factory=lambda: [])
    reminder_images: list[model.ImageURLPart] = field(default_factory=lambda: [])


@dataclass
class AssistantGroup:
    """Aggregated assistant message group."""

    text_content: str | None = None
    tool_calls: list[model.ToolCallItem] = field(default_factory=lambda: [])
    reasoning_items: list[model.ReasoningTextItem | model.ReasoningEncryptedItem] = field(default_factory=lambda: [])


MessageGroup = UserGroup | ToolGroup | AssistantGroup


def _kind_of(item: model.ConversationItem) -> GroupKind:
    if isinstance(
        item,
        (model.ReasoningTextItem, model.ReasoningEncryptedItem, model.AssistantMessageItem, model.ToolCallItem),
    ):
        return GroupKind.ASSISTANT
    if isinstance(item, model.UserMessageItem):
        return GroupKind.USER
    if isinstance(item, model.ToolResultItem):
        return GroupKind.TOOL
    if isinstance(item, model.DeveloperMessageItem):
        return GroupKind.DEVELOPER
    return GroupKind.OTHER


def group_response_items_gen(
    items: Iterable[model.ConversationItem],
) -> Iterator[tuple[GroupKind, list[model.ConversationItem]]]:
    """Group response items into sublists with predictable attachment rules.

    - Consecutive assistant-side items (ReasoningTextItem | ReasoningEncryptedItem |
      AssistantMessageItem | ToolCallItem) group together.
    - Consecutive UserMessage group together.
    - Each ToolMessage (ToolResultItem) is a single group, but allow following
      DeveloperMessage to attach to it.
    - DeveloperMessage only attaches to the previous UserMessage/ToolMessage group.
    """
    buffer: list[model.ConversationItem] = []
    buffer_kind: GroupKind | None = None

    def flush() -> Iterator[tuple[GroupKind, list[model.ConversationItem]]]:
        """Yield current group and reset buffer state."""

        nonlocal buffer, buffer_kind
        if buffer_kind is not None and buffer:
            yield (buffer_kind, buffer)
        buffer = []
        buffer_kind = None

    for item in items:
        item_kind = _kind_of(item)
        if item_kind == GroupKind.OTHER:
            continue

        # Developer messages only attach to existing user/tool group.
        if item_kind == GroupKind.DEVELOPER:
            if buffer_kind in (GroupKind.USER, GroupKind.TOOL):
                buffer.append(item)
            continue

        # Start a new group when there is no active buffer yet.
        if buffer_kind is None:
            buffer_kind = GroupKind.TOOL if item_kind == GroupKind.TOOL else item_kind
            buffer = [item]
            continue

        # Tool messages always form a standalone group.
        if item_kind == GroupKind.TOOL:
            yield from flush()
            buffer_kind = GroupKind.TOOL
            buffer = [item]
            continue

        # Same non-tool kind: extend current group.
        if item_kind == buffer_kind:
            buffer.append(item)
            continue

        # Different non-tool kind: close previous group and start a new one.
        yield from flush()
        buffer_kind = item_kind
        buffer = [item]

    if buffer_kind is not None and buffer:
        yield (buffer_kind, buffer)


def parse_message_groups(history: list[model.ConversationItem]) -> list[MessageGroup]:
    """Parse conversation history into aggregated message groups.

    This is the shared grouping logic for Anthropic, OpenAI-compatible, and OpenRouter.
    Each provider then converts these groups to their specific API format.
    """
    groups: list[MessageGroup] = []

    for kind, items in group_response_items_gen(history):
        match kind:
            case GroupKind.OTHER:
                continue
            case GroupKind.USER:
                group = UserGroup()
                for item in items:
                    if isinstance(item, (model.UserMessageItem, model.DeveloperMessageItem)):
                        if item.content:
                            group.text_parts.append(item.content + "\n")
                        if item.images:
                            group.images.extend(item.images)
                groups.append(group)

            case GroupKind.TOOL:
                if not items or not isinstance(items[0], model.ToolResultItem):
                    continue
                tool_result = items[0]
                group = ToolGroup(tool_result=tool_result)
                for item in items[1:]:
                    if isinstance(item, model.DeveloperMessageItem):
                        if item.content:
                            group.reminder_texts.append(item.content)
                        if item.images:
                            group.reminder_images.extend(item.images)
                groups.append(group)

            case GroupKind.ASSISTANT:
                group = AssistantGroup()
                for item in items:
                    match item:
                        case model.AssistantMessageItem():
                            if item.content:
                                if group.text_content is None:
                                    group.text_content = item.content
                                else:
                                    group.text_content += item.content
                        case model.ToolCallItem():
                            group.tool_calls.append(item)
                        case model.ReasoningTextItem():
                            group.reasoning_items.append(item)
                        case model.ReasoningEncryptedItem():
                            group.reasoning_items.append(item)
                        case _:
                            pass
                groups.append(group)

            case GroupKind.DEVELOPER:
                pass

    return groups


def merge_reminder_text(tool_output: str | None, reminder_texts: list[str]) -> str:
    """Merge tool output with reminder texts."""
    base = tool_output or ""
    if reminder_texts:
        base += "\n" + "\n".join(reminder_texts)
    return base


def apply_config_defaults(param: "LLMCallParameter", config: "LLMConfigParameter") -> "LLMCallParameter":
    """Apply config defaults to LLM call parameters."""
    if param.model is None:
        param.model = config.model
    if param.temperature is None:
        param.temperature = config.temperature
    if param.max_tokens is None:
        param.max_tokens = config.max_tokens
    if param.context_limit is None:
        param.context_limit = config.context_limit
    if param.verbosity is None:
        param.verbosity = config.verbosity
    if param.thinking is None:
        param.thinking = config.thinking
    if param.provider_routing is None:
        param.provider_routing = config.provider_routing

    if param.model is None:
        raise ValueError("Model is required")
    if param.max_tokens is None:
        param.max_tokens = const.DEFAULT_MAX_TOKENS
    if param.temperature is None:
        param.temperature = const.DEFAULT_TEMPERATURE
    if param.thinking is not None and param.thinking.type == "enabled" and param.thinking.budget_tokens is None:
        param.thinking.budget_tokens = const.DEFAULT_ANTHROPIC_THINKING_BUDGET_TOKENS

    if param.model and "gpt-5" in param.model:
        param.temperature = 1.0  # Required for GPT-5

    return param
