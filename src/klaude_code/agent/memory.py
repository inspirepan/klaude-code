"""Memory file loading and management.

This module handles CLAUDE.md and AGENTS.md memory files - discovery, loading,
and providing summaries for UI display.
"""

from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel

from klaude_code.const import ProjectPaths, find_git_repo_root, project_key_from_path

MEMORY_FILE_NAMES = ["AGENTS.md", "CLAUDE.md", "AGENT.md"]

USER_MEMORY_INSTRUCTION = "user's private global instructions for all projects"
PROJECT_MEMORY_INSTRUCTION = "project instructions, checked into the codebase"

AUTO_MEMORY_FILE = "MEMORY.md"
AUTO_MEMORY_MAX_LINES = 200
MEMORY_MAX_BYTES_PER_FILE = 4096


class Memory(BaseModel):
    """Represents a loaded memory file."""

    path: str
    instruction: str
    content: str


def get_project_memory_dirs(*, work_dir: Path) -> list[Path]:
    """Return project memory search directories, including git root when available."""
    work_dir = work_dir.resolve()
    dirs = [work_dir, work_dir / ".claude", work_dir / ".agents"]

    git_root = find_git_repo_root(work_dir=work_dir)
    if git_root is not None:
        dirs.extend([git_root, git_root / ".claude", git_root / ".agents"])

    deduped_dirs: list[Path] = []
    seen: set[Path] = set()
    for d in dirs:
        resolved = d.resolve()
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
    for d in user_dirs:
        for fname in MEMORY_FILE_NAMES:
            paths.append((d / fname, USER_MEMORY_INSTRUCTION))
    for d in project_dirs:
        for fname in MEMORY_FILE_NAMES:
            paths.append((d / fname, PROJECT_MEMORY_INSTRUCTION))
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
    """Format a single memory file content for display."""
    return f"Contents of {memory.path} ({memory.instruction}):\n\n{memory.content}"


def format_memories_attachment(memories: list[Memory], include_header: bool = True) -> str:
    """Format memory files into a system-reminder attachment string."""
    memories_str = "\n\n".join(format_memory_content(m) for m in memories)
    if include_header:
        return f"""<system-reminder>
Loaded memory files. Follow these instructions. Do not mention them to the user unless explicitly asked.

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
        result += (
            f"\n\n> This memory file was truncated ({MEMORY_MAX_BYTES_PER_FILE} byte limit). "
            f"Use the Read tool to view the complete file at: {path}"
        )
    return result


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
    seen_dirs: set[Path] = set()
    seen_resolved: set[Path] = set()

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
            if current_dir in seen_dirs:
                continue
            seen_dirs.add(current_dir)
            for fname in MEMORY_FILE_NAMES:
                mem_path = current_dir / fname
                path_str = str(mem_path)
                if not mem_path.exists() or not mem_path.is_file():
                    continue
                # Deduplicate symlinks / hardlinks pointing to the same file
                try:
                    resolved = mem_path.resolve()
                except OSError:
                    resolved = mem_path
                if resolved in seen_resolved:
                    continue
                seen_resolved.add(resolved)
                if is_memory_loaded(path_str):
                    continue
                try:
                    text = mem_path.read_text(encoding="utf-8", errors="replace")
                    text = truncate_memory_content(text, path_str)
                except (PermissionError, UnicodeDecodeError, OSError):
                    continue
                mark_memory_loaded(path_str)
                memories.append(
                    Memory(
                        path=path_str,
                        instruction="project instructions, discovered near last accessed path",
                        content=text,
                    )
                )

    return memories


def get_auto_memory_path(work_dir: Path) -> Path:
    """Return the path to the per-project MEMORY.md (may not exist yet).

    Creates the memory directory if it does not exist.
    """
    paths = ProjectPaths(project_key=project_key_from_path(work_dir))
    paths.memory_dir.mkdir(parents=True, exist_ok=True)
    return paths.memory_dir / AUTO_MEMORY_FILE


def load_auto_memory(work_dir: Path) -> Memory | None:
    """Load the per-project MEMORY.md from the auto-memory directory.

    Returns the Memory object if the file exists, or None.
    Content is truncated to AUTO_MEMORY_MAX_LINES lines.
    """
    memory_path = get_auto_memory_path(work_dir)
    if not memory_path.exists() or not memory_path.is_file():
        return None
    try:
        text = memory_path.read_text(encoding="utf-8", errors="replace")
    except (PermissionError, UnicodeDecodeError, OSError):
        return None
    lines = text.splitlines()
    instruction = "auto memory, persisted across sessions"
    if len(lines) > AUTO_MEMORY_MAX_LINES:
        total_lines = len(lines)
        text = "\n".join(lines[:AUTO_MEMORY_MAX_LINES])
        instruction += f" (truncated to first {AUTO_MEMORY_MAX_LINES} lines from {total_lines} total lines)"
    return Memory(path=str(memory_path), instruction=instruction, content=text)
