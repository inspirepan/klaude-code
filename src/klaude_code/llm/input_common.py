"""Common utilities for converting conversation history to LLM input formats.

This module provides shared abstractions for providers that require message grouping
(Anthropic, OpenAI-compatible, OpenRouter). The Responses API doesn't need this
since it uses a flat item list matching our internal protocol.
"""

from collections.abc import Iterator
from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable

from klaude_code.protocol.model import (
    AssistantMessageItem,
    ConversationItem,
    DeveloperMessageItem,
    ImageURLPart,
    ReasoningEncryptedItem,
    ReasoningTextItem,
    ToolCallItem,
    ToolResultItem,
    UserMessageItem,
)


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
    images: list[ImageURLPart] = field(default_factory=lambda: [])


@dataclass
class ToolGroup:
    """Aggregated tool result group (ToolResultItem + trailing DeveloperMessageItems)."""

    tool_result: ToolResultItem
    reminder_texts: list[str] = field(default_factory=lambda: [])
    reminder_images: list[ImageURLPart] = field(default_factory=lambda: [])


@dataclass
class AssistantGroup:
    """Aggregated assistant message group."""

    text_content: str | None = None
    tool_calls: list[ToolCallItem] = field(default_factory=lambda: [])
    reasoning_text: list[ReasoningTextItem] = field(default_factory=lambda: [])
    reasoning_encrypted: list[ReasoningEncryptedItem] = field(default_factory=lambda: [])
    # Preserve original ordering of reasoning items for providers that
    # need to emit them as an ordered stream (e.g. OpenRouter).
    reasoning_items: list[ReasoningTextItem | ReasoningEncryptedItem] = field(default_factory=lambda: [])


MessageGroup = UserGroup | ToolGroup | AssistantGroup


def _kind_of(item: ConversationItem) -> GroupKind:
    if isinstance(item, (ReasoningTextItem, ReasoningEncryptedItem, AssistantMessageItem, ToolCallItem)):
        return GroupKind.ASSISTANT
    if isinstance(item, UserMessageItem):
        return GroupKind.USER
    if isinstance(item, ToolResultItem):
        return GroupKind.TOOL
    if isinstance(item, DeveloperMessageItem):
        return GroupKind.DEVELOPER
    return GroupKind.OTHER


def group_response_items_gen(
    items: Iterable[ConversationItem],
) -> Iterator[tuple[GroupKind, list[ConversationItem]]]:
    """Group response items into sublists with predictable attachment rules.

    - Consecutive assistant-side items (ReasoningTextItem | ReasoningEncryptedItem |
      AssistantMessageItem | ToolCallItem) group together.
    - Consecutive UserMessage group together.
    - Each ToolMessage (ToolResultItem) is a single group, but allow following
      DeveloperMessage to attach to it.
    - DeveloperMessage only attaches to the previous UserMessage/ToolMessage group.
    """
    buffer: list[ConversationItem] = []
    buffer_kind: GroupKind | None = None

    def flush() -> Iterator[tuple[GroupKind, list[ConversationItem]]]:
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


def parse_message_groups(history: list[ConversationItem]) -> list[MessageGroup]:
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
                    if isinstance(item, (UserMessageItem, DeveloperMessageItem)):
                        if item.content:
                            group.text_parts.append(item.content)
                        if item.images:
                            group.images.extend(item.images)
                groups.append(group)

            case GroupKind.TOOL:
                if not items or not isinstance(items[0], ToolResultItem):
                    continue
                tool_result = items[0]
                group = ToolGroup(tool_result=tool_result)
                for item in items[1:]:
                    if isinstance(item, DeveloperMessageItem):
                        if item.content:
                            group.reminder_texts.append(item.content)
                        if item.images:
                            group.reminder_images.extend(item.images)
                groups.append(group)

            case GroupKind.ASSISTANT:
                group = AssistantGroup()
                for item in items:
                    match item:
                        case AssistantMessageItem():
                            if item.content:
                                if group.text_content is None:
                                    group.text_content = item.content
                                else:
                                    group.text_content += item.content
                        case ToolCallItem():
                            group.tool_calls.append(item)
                        case ReasoningTextItem():
                            group.reasoning_text.append(item)
                            group.reasoning_items.append(item)
                        case ReasoningEncryptedItem():
                            group.reasoning_encrypted.append(item)
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
