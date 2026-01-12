"""Memory file loading and management.

This module handles CLAUDE.md and AGENTS.md memory files - discovery, loading,
and providing summaries for UI display.
"""

from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel

MEMORY_FILE_NAMES = ["CLAUDE.md", "AGENTS.md", "AGENT.md"]


class Memory(BaseModel):
    """Represents a loaded memory file."""

    path: str
    instruction: str
    content: str


def get_memory_paths(*, work_dir: Path) -> list[tuple[Path, str]]:
    """Return all possible memory file paths with their descriptions."""
    user_dirs = [Path.home() / ".claude", Path.home() / ".codex"]
    project_dirs = [work_dir, work_dir / ".claude"]

    paths: list[tuple[Path, str]] = []
    for d in user_dirs:
        for fname in MEMORY_FILE_NAMES:
            paths.append((d / fname, "user's private global instructions for all projects"))
    for d in project_dirs:
        for fname in MEMORY_FILE_NAMES:
            paths.append((d / fname, "project instructions, checked into the codebase"))
    return paths


def get_existing_memory_files(*, work_dir: Path) -> dict[str, list[str]]:
    """Return existing memory file paths grouped by location (user/project)."""
    result: dict[str, list[str]] = {"user": [], "project": []}
    work_dir = work_dir.resolve()

    for memory_path, _instruction in get_memory_paths(work_dir=work_dir):
        if memory_path.exists() and memory_path.is_file():
            path_str = str(memory_path)
            resolved = memory_path.resolve()
            try:
                resolved.relative_to(work_dir)
                result["project"].append(path_str)
            except ValueError:
                result["user"].append(path_str)

    return result


def get_existing_memory_paths_by_location(*, work_dir: Path) -> dict[str, list[str]]:
    """Return existing memory file paths grouped by location for WelcomeEvent."""
    result = get_existing_memory_files(work_dir=work_dir)
    if not result.get("user") and not result.get("project"):
        return {}
    return result


def format_memory_content(memory: Memory) -> str:
    """Format a single memory file content for display."""
    return f"Contents of {memory.path} ({memory.instruction}):\n\n{memory.content}"


def format_memories_reminder(memories: list[Memory], include_header: bool = True) -> str:
    """Format memory files into a system reminder string."""
    memories_str = "\n\n".join(format_memory_content(m) for m in memories)
    if include_header:
        return f"""<system-reminder>
Loaded memory files. Follow these instructions. Do not mention them to the user unless explicitly asked.

{memories_str}
</system-reminder>"""
    return f"<system-reminder>{memories_str}\n</system-reminder>"


def discover_memory_files_near_paths(
    paths: list[str],
    *,
    work_dir: Path,
    is_memory_loaded: Callable[[str], bool],
    mark_memory_loaded: Callable[[str], None],
) -> list[Memory]:
    """Discover and load CLAUDE.md/AGENTS.md from directories containing accessed files.

    Args:
        paths: List of file paths that have been accessed.
        is_memory_loaded: Callback to check if a memory file is already loaded.
        mark_memory_loaded: Callback to mark a memory file as loaded.

    Returns:
        List of newly discovered Memory objects.
    """
    memories: list[Memory] = []
    work_dir = work_dir.resolve()
    seen_memory_files: set[str] = set()

    for p_str in paths:
        p = Path(p_str)
        full = (work_dir / p).resolve() if not p.is_absolute() else p.resolve()
        try:
            _ = full.relative_to(work_dir)
        except ValueError:
            continue

        deepest_dir = full if full.is_dir() else full.parent

        try:
            rel_parts = deepest_dir.relative_to(work_dir).parts
        except ValueError:
            continue

        current_dir = work_dir
        for part in rel_parts:
            current_dir = current_dir / part
            for fname in MEMORY_FILE_NAMES:
                mem_path = current_dir / fname
                mem_path_str = str(mem_path)
                if mem_path_str in seen_memory_files or is_memory_loaded(mem_path_str):
                    continue
                if mem_path.exists() and mem_path.is_file():
                    try:
                        text = mem_path.read_text(encoding="utf-8", errors="replace")
                    except (PermissionError, UnicodeDecodeError, OSError):
                        continue
                    mark_memory_loaded(mem_path_str)
                    seen_memory_files.add(mem_path_str)
                    memories.append(
                        Memory(
                            path=mem_path_str,
                            instruction="project instructions, discovered near last accessed path",
                            content=text,
                        )
                    )

    return memories
