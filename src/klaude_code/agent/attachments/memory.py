from __future__ import annotations

from klaude_code.agent.attachment_prompts import fmt_auto_memory_hint, fmt_memory_truncated
from klaude_code.agent.memory import (
    Memory,
    discover_memory_files_near_paths,
    format_memories_attachment,
    get_auto_memory_path,
    get_memory_paths,
    load_auto_memory,
    truncate_memory_content,
)
from klaude_code.protocol import message
from klaude_code.protocol.models import DeveloperUIExtra, DeveloperUIItem, MemoryFileLoaded, MemoryLoadedUIItem
from klaude_code.session import Session

from .state import is_memory_loaded, mark_memory_loaded

MEMORY_MAX_SESSION_BYTES = 60 * 1024


def _count_memory_session_bytes(session: Session) -> int:
    total = 0
    for item in session.conversation_history:
        if isinstance(item, message.DeveloperMessage) and item.ui_extra:
            for ui_item in item.ui_extra.items:
                if isinstance(ui_item, MemoryLoadedUIItem):
                    total += sum(len(part.text.encode("utf-8")) for part in item.parts if isinstance(part, message.TextPart))
                    break
    return total


async def memory_attachment(session: Session) -> message.DeveloperMessage | None:
    """CLAUDE.md AGENTS.md and per-project MEMORY.md with budget limits."""

    session_bytes = _count_memory_session_bytes(session)
    if session_bytes >= MEMORY_MAX_SESSION_BYTES:
        return None

    memories: list[Memory] = []
    remaining_budget = MEMORY_MAX_SESSION_BYTES - session_bytes
    for memory_path, instruction in get_memory_paths(work_dir=session.work_dir):
        path_str = str(memory_path)
        if not (memory_path.exists() and memory_path.is_file()) or is_memory_loaded(session, path_str):
            continue
        try:
            text = truncate_memory_content(memory_path.read_text(encoding="utf-8", errors="replace"), path_str)
            text_bytes = len(text.encode("utf-8"))
            if text_bytes > remaining_budget:
                if remaining_budget > 256:
                    text = text.encode("utf-8")[:remaining_budget].decode("utf-8", errors="ignore")
                    text += fmt_memory_truncated(MEMORY_MAX_SESSION_BYTES)
                    text_bytes = len(text.encode("utf-8"))
                else:
                    mark_memory_loaded(session, path_str)
                    continue
            remaining_budget -= text_bytes
            mark_memory_loaded(session, path_str)
            memories.append(Memory(path=path_str, instruction=instruction, content=text))
        except (PermissionError, UnicodeDecodeError, OSError):
            continue

    auto_memory_hint = ""
    auto_mem = load_auto_memory(session.work_dir)
    if auto_mem is not None:
        if not is_memory_loaded(session, auto_mem.path):
            auto_mem_content = truncate_memory_content(auto_mem.content, auto_mem.path)
            auto_mem_bytes = len(auto_mem_content.encode("utf-8"))
            if auto_mem_bytes <= remaining_budget:
                remaining_budget -= auto_mem_bytes
                mark_memory_loaded(session, auto_mem.path)
                memories.append(Memory(path=auto_mem.path, instruction=auto_mem.instruction, content=auto_mem_content))
            else:
                mark_memory_loaded(session, auto_mem.path)
    else:
        auto_memory_path = get_auto_memory_path(session.work_dir)
        path_str = str(auto_memory_path)
        if not is_memory_loaded(session, path_str):
            mark_memory_loaded(session, path_str)
            auto_memory_hint = fmt_auto_memory_hint(auto_memory_path)

    if not memories and not auto_memory_hint:
        return None

    ui_items: list[DeveloperUIItem] = (
        [MemoryLoadedUIItem(files=[MemoryFileLoaded(path=memory.path) for memory in memories])] if memories else []
    )
    content_text = format_memories_attachment(memories, include_header=True) if memories else ""
    if auto_memory_hint:
        if content_text:
            content_text = content_text.replace("</system-reminder>", f"{auto_memory_hint}\n</system-reminder>")
        else:
            content_text = f"<system-reminder>{auto_memory_hint}\n</system-reminder>"
    return message.DeveloperMessage(
        parts=message.text_parts_from_str(content_text),
        attachment_position="prepend",
        ui_extra=DeveloperUIExtra(items=ui_items),
    )


async def last_path_memory_attachment(session: Session) -> message.DeveloperMessage | None:
    """Load CLAUDE.md/AGENTS.md from directories containing files in file_tracker."""

    if not session.file_tracker:
        return None

    memories = discover_memory_files_near_paths(
        list(session.file_tracker.keys()),
        work_dir=session.work_dir,
        is_memory_loaded=lambda path: is_memory_loaded(session, path),
        mark_memory_loaded=lambda path: mark_memory_loaded(session, path),
    )
    if not memories:
        return None
    return message.DeveloperMessage(
        parts=message.text_parts_from_str(format_memories_attachment(memories, include_header=False)),
        attachment_position="prepend",
        ui_extra=DeveloperUIExtra(items=[MemoryLoadedUIItem(files=[MemoryFileLoaded(path=memory.path) for memory in memories])]),
    )