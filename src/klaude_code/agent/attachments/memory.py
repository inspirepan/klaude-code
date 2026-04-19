from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel

from klaude_code.const import ProjectPaths, find_git_repo_root, project_key_from_path
from klaude_code.prompts.attachments import (
    AUTO_MEMORY_HINT_TEMPLATE,
    AUTO_MEMORY_INSTRUCTION,
    DISCOVERED_MEMORY_INSTRUCTION,
    MEMORY_FILE_TRUNCATED_TEMPLATE,
    MEMORY_HEADER,
    MEMORY_TRUNCATED_TEMPLATE,
    PROJECT_MEMORY_INSTRUCTION,
    USER_MEMORY_INSTRUCTION,
)
from klaude_code.protocol import message
from klaude_code.protocol.models import DeveloperUIExtra, DeveloperUIItem, MemoryFileLoaded, MemoryLoadedUIItem
from klaude_code.session import Session

from .state import is_memory_loaded, mark_memory_loaded

MEMORY_FILE_NAMES = ["AGENTS.md", "CLAUDE.md", "AGENT.md"]

AUTO_MEMORY_FILE = "MEMORY.md"
AUTO_MEMORY_MAX_LINES = 200
MEMORY_MAX_BYTES_PER_FILE = 4096
MEMORY_MAX_SESSION_BYTES = 60 * 1024


class Memory(BaseModel):
    """Represents a loaded memory file."""

    path: str
    instruction: str
    content: str


def _fmt_memory_truncated(budget_bytes: int) -> str:
    return MEMORY_TRUNCATED_TEMPLATE.format(budget_bytes=budget_bytes)


def _fmt_auto_memory_hint(auto_memory_path: Path) -> str:
    return AUTO_MEMORY_HINT_TEMPLATE.format(auto_memory_path=auto_memory_path)


def get_project_memory_dirs(*, work_dir: Path) -> list[Path]:
    """Return project memory search directories, including git root when available."""

    work_dir = work_dir.resolve()
    dirs = [work_dir, work_dir / ".claude", work_dir / ".agents"]

    git_root = find_git_repo_root(work_dir=work_dir)
    if git_root is not None:
        dirs.extend([git_root, git_root / ".claude", git_root / ".agents"])

    deduped_dirs: list[Path] = []
    seen: set[Path] = set()
    for directory in dirs:
        resolved = directory.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        deduped_dirs.append(resolved)
    return deduped_dirs


def get_memory_paths(*, work_dir: Path) -> list[tuple[Path, str]]:
    """Return all possible memory file paths with their descriptions."""

    user_dirs = [Path.home() / ".claude", Path.home() / ".codex", Path.home() / ".klaude", Path.home() / ".agents"]
    project_dirs = get_project_memory_dirs(work_dir=work_dir)

    paths: list[tuple[Path, str]] = []
    for directory in user_dirs:
        for file_name in MEMORY_FILE_NAMES:
            paths.append((directory / file_name, USER_MEMORY_INSTRUCTION))
    for directory in project_dirs:
        for file_name in MEMORY_FILE_NAMES:
            paths.append((directory / file_name, PROJECT_MEMORY_INSTRUCTION))
    return paths


def get_existing_memory_files(*, work_dir: Path) -> dict[str, list[str]]:
    """Return existing memory file paths grouped by location (user/project)."""

    result: dict[str, list[str]] = {"user": [], "project": []}
    work_dir = work_dir.resolve()

    for memory_path, instruction in get_memory_paths(work_dir=work_dir):
        if memory_path.exists() and memory_path.is_file():
            path_str = str(memory_path)
            if instruction == PROJECT_MEMORY_INSTRUCTION:
                result["project"].append(path_str)
            else:
                result["user"].append(path_str)

    return result


def get_existing_memory_paths_by_location(*, work_dir: Path) -> dict[str, list[str]]:
    """Return existing memory file paths grouped by location for WelcomeEvent."""

    result = get_existing_memory_files(work_dir=work_dir)

    paths = ProjectPaths(project_key=project_key_from_path(work_dir))
    auto_memory_path = paths.memory_dir / AUTO_MEMORY_FILE
    if auto_memory_path.exists() and auto_memory_path.is_file():
        result.setdefault("project", []).append(str(auto_memory_path))

    if not any(result.values()):
        return {}
    return result


def format_memory_content(memory: Memory) -> str:
    return f"Contents of {memory.path} ({memory.instruction}):\n\n{memory.content}"


def format_memories_attachment(memories: list[Memory], include_header: bool = True) -> str:
    memories_str = "\n\n".join(format_memory_content(memory) for memory in memories)
    if include_header:
        return f"""<system-reminder>
{MEMORY_HEADER}

{memories_str}
</system-reminder>"""
    return f"<system-reminder>{memories_str}\n</system-reminder>"


def truncate_memory_content(text: str, path: str) -> str:
    """Truncate memory content to the shared per-file limits used by attachments."""

    lines = text.splitlines()
    truncated = False

    if len(lines) > AUTO_MEMORY_MAX_LINES:
        lines = lines[:AUTO_MEMORY_MAX_LINES]
        truncated = True

    result = "\n".join(lines)
    if len(result.encode("utf-8")) > MEMORY_MAX_BYTES_PER_FILE:
        encoded = result.encode("utf-8")[:MEMORY_MAX_BYTES_PER_FILE]
        result = encoded.decode("utf-8", errors="ignore")
        truncated = True

    if truncated:
        result += MEMORY_FILE_TRUNCATED_TEMPLATE.format(max_bytes=MEMORY_MAX_BYTES_PER_FILE, path=path)
    return result


def discover_memory_files_near_paths(
    paths: list[str],
    *,
    work_dir: Path,
    is_memory_loaded: Callable[[str], bool],
    mark_memory_loaded: Callable[[str], None],
) -> list[Memory]:
    """Discover and load memory files from directories containing accessed files."""

    memories: list[Memory] = []
    work_dir = work_dir.resolve()
    seen_dirs: set[Path] = set()
    seen_resolved: set[Path] = set()

    for path_str in paths:
        path = Path(path_str)
        full_path = (work_dir / path).resolve() if not path.is_absolute() else path.resolve()
        try:
            _ = full_path.relative_to(work_dir)
        except ValueError:
            continue

        deepest_dir = full_path if full_path.is_dir() else full_path.parent
        try:
            rel_parts = deepest_dir.relative_to(work_dir).parts
        except ValueError:
            continue

        current_dir = work_dir
        for part in rel_parts:
            current_dir = current_dir / part
            if current_dir in seen_dirs:
                continue
            seen_dirs.add(current_dir)
            for file_name in MEMORY_FILE_NAMES:
                memory_path = current_dir / file_name
                memory_path_str = str(memory_path)
                if not memory_path.exists() or not memory_path.is_file():
                    continue
                try:
                    resolved = memory_path.resolve()
                except OSError:
                    resolved = memory_path
                if resolved in seen_resolved:
                    continue
                seen_resolved.add(resolved)
                if is_memory_loaded(memory_path_str):
                    continue
                try:
                    text = memory_path.read_text(encoding="utf-8", errors="replace")
                    text = truncate_memory_content(text, memory_path_str)
                except (PermissionError, UnicodeDecodeError, OSError):
                    continue
                mark_memory_loaded(memory_path_str)
                memories.append(
                    Memory(
                        path=memory_path_str,
                        instruction=DISCOVERED_MEMORY_INSTRUCTION,
                        content=text,
                    )
                )

    return memories


def get_auto_memory_path(work_dir: Path) -> Path:
    """Return the path to the per-project MEMORY.md (may not exist yet)."""

    paths = ProjectPaths(project_key=project_key_from_path(work_dir))
    paths.memory_dir.mkdir(parents=True, exist_ok=True)
    return paths.memory_dir / AUTO_MEMORY_FILE


def load_auto_memory(work_dir: Path) -> Memory | None:
    """Load the per-project MEMORY.md from the auto-memory directory."""

    memory_path = get_auto_memory_path(work_dir)
    if not memory_path.exists() or not memory_path.is_file():
        return None
    try:
        text = memory_path.read_text(encoding="utf-8", errors="replace")
    except (PermissionError, UnicodeDecodeError, OSError):
        return None
    lines = text.splitlines()
    instruction = AUTO_MEMORY_INSTRUCTION
    if len(lines) > AUTO_MEMORY_MAX_LINES:
        total_lines = len(lines)
        text = "\n".join(lines[:AUTO_MEMORY_MAX_LINES])
        instruction += f" (truncated to first {AUTO_MEMORY_MAX_LINES} lines from {total_lines} total lines)"
    return Memory(path=str(memory_path), instruction=instruction, content=text)


def _count_memory_session_bytes(session: Session) -> int:
    total = 0
    for item in session.conversation_history:
        if isinstance(item, message.DeveloperMessage) and item.ui_extra:
            for ui_item in item.ui_extra.items:
                if isinstance(ui_item, MemoryLoadedUIItem):
                    total += sum(
                        len(part.text.encode("utf-8")) for part in item.parts if isinstance(part, message.TextPart)
                    )
                    break
    return total


async def memory_attachment(session: Session) -> message.DeveloperMessage | None:
    """Load global, project, and auto memory files with a session budget."""

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
                    text += _fmt_memory_truncated(MEMORY_MAX_SESSION_BYTES)
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
    auto_memory = load_auto_memory(session.work_dir)
    if auto_memory is not None:
        if not is_memory_loaded(session, auto_memory.path):
            auto_memory_content = truncate_memory_content(auto_memory.content, auto_memory.path)
            auto_memory_bytes = len(auto_memory_content.encode("utf-8"))
            if auto_memory_bytes <= remaining_budget:
                remaining_budget -= auto_memory_bytes
                mark_memory_loaded(session, auto_memory.path)
                memories.append(
                    Memory(path=auto_memory.path, instruction=auto_memory.instruction, content=auto_memory_content)
                )
            else:
                mark_memory_loaded(session, auto_memory.path)
    else:
        auto_memory_path = get_auto_memory_path(session.work_dir)
        path_str = str(auto_memory_path)
        if not is_memory_loaded(session, path_str):
            mark_memory_loaded(session, path_str)
            auto_memory_hint = _fmt_auto_memory_hint(auto_memory_path)

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
    """Load memory files discovered near recently accessed paths."""

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
        ui_extra=DeveloperUIExtra(
            items=[MemoryLoadedUIItem(files=[MemoryFileLoaded(path=memory.path) for memory in memories])]
        ),
    )
