import asyncio
import difflib
import hashlib
import logging
import re
import shlex
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path

from klaude_code.core.memory import (
    AUTO_MEMORY_MAX_LINES,
    Memory,
    discover_memory_files_near_paths,
    format_memories_attachment,
    format_memory_content,
    get_auto_memory_path,
    get_memory_paths,
    load_auto_memory,
)
from klaude_code.core.tool import BashTool, ReadTool, build_todo_context
from klaude_code.core.tool.context import ToolContext
from klaude_code.core.tool.file._utils import hash_text_sha256
from klaude_code.protocol import message, model, tools
from klaude_code.session import Session
from klaude_code.skill import get_skill

logger = logging.getLogger(__name__)

# Match @ preceded by whitespace, start of line, or → (ReadTool line number arrow)
# Supports optional line range suffix: @file.txt#L10-20 or @file.txt#L10
AT_FILE_PATTERN = re.compile(r'(?:(?<!\S)|(?<=\u2192))@("(?P<quoted>[^\"]+)"|(?P<plain>\S+))')

# Memory budget limits (inspired by Claude Code's attachment system)
MEMORY_MAX_BYTES_PER_FILE = 4096
MEMORY_MAX_SESSION_BYTES = 60 * 1024

# Todo attachment configuration
TODO_ATTACHMENT_TURNS_SINCE_WRITE = 10
TODO_ATTACHMENT_TURNS_BETWEEN = 10

# Match /skill:xxx or //skill:xxx inline (at start of line or after whitespace).
# Require token boundary after the skill name to avoid matching paths like
# /Users/root/code.
SLASH_SKILL_PATTERN = re.compile(r"(?:^|\s)(?://|/)skill:(?P<skill>[^\s/]+)(?=\s|$)")


class AtFileRef:
    """Parsed @file reference with optional line range."""

    __slots__ = ("line_end", "line_start", "path")

    def __init__(self, path: str, line_start: int | None = None, line_end: int | None = None) -> None:
        self.path = path
        self.line_start = line_start
        self.line_end = line_end


def _parse_at_file_ref(raw: str) -> AtFileRef:
    """Parse a raw @-mention string into path + optional line range.

    Supports: file.txt, file.txt#L10, file.txt#L10-20

    To avoid breaking filenames that literally contain ``#L``, the suffix is
    only stripped when the path-without-suffix resolves to an existing file
    and the full raw path does not.
    """
    match = re.match(r"^(.+?)#L(\d+)(?:-(\d+))?$", raw)
    if not match:
        return AtFileRef(raw)

    base_path = match.group(1)
    # If the raw string is itself a valid path, treat it literally
    if Path(raw).resolve().exists():
        return AtFileRef(raw)
    # Only interpret as line range if the base path exists
    if not Path(base_path).resolve().exists():
        return AtFileRef(raw)

    line_start = int(match.group(2))
    line_end_str = match.group(3)
    line_end = int(line_end_str) if line_end_str else line_start
    return AtFileRef(base_path, line_start, line_end)


def get_at_patterns(session: Session) -> list[AtFileRef]:
    """Get @ patterns from the last user message."""
    for item in reversed(session.conversation_history):
        if isinstance(item, message.ToolResultMessage):
            break
        if isinstance(item, message.UserMessage):
            content = message.join_text_parts(item.parts)
            refs: list[AtFileRef] = []
            if "@" in content:
                for match in AT_FILE_PATTERN.finditer(content):
                    path_str = match.group("quoted") or match.group("plain")
                    if path_str:
                        refs.append(_parse_at_file_ref(path_str))
            return refs
    return []


def get_skills_from_user_input(session: Session) -> list[str]:
    """Get explicit skill references from last user input."""
    for item in reversed(session.conversation_history):
        if isinstance(item, message.ToolResultMessage):
            return []
        if isinstance(item, message.UserMessage):
            content = message.join_text_parts(item.parts)
            seen: set[str] = set()
            result: list[str] = []
            for m in SLASH_SKILL_PATTERN.finditer(content):
                name = m.group("skill")
                if name not in seen:
                    seen.add(name)
                    result.append(name)
            return result
    return []


def _is_tracked_file_unchanged(session: Session, path: str) -> bool:
    status = session.file_tracker.get(path)
    if status is None or status.content_sha256 is None:
        return False

    try:
        current_mtime = Path(path).stat().st_mtime
    except (OSError, FileNotFoundError):
        return False

    if current_mtime == status.mtime:
        return True

    current_sha256 = _compute_file_content_sha256(path)
    return current_sha256 is not None and current_sha256 == status.content_sha256


async def _load_at_file(
    session: Session,
    ref: AtFileRef,
    at_ops: list[model.AtFileOp],
    formatted_blocks: list[str],
    collected_images: list[message.ImageURLPart],
    collected_image_paths: list[str],
    discovered_memories: list[Memory],
) -> None:
    """Load a single @ file or directory reference."""
    path = Path(ref.path).resolve()
    path_str = str(path)

    tool_context = ToolContext(
        file_tracker=session.file_tracker,
        todo_context=build_todo_context(session),
        session_id=session.id,
        work_dir=session.work_dir,
    )

    if path.exists() and path.is_file():
        # Already-read optimization: if file is unchanged and no line range specified,
        # emit a lightweight "already in context" note instead of re-reading.
        if _is_tracked_file_unchanged(session, path_str) and ref.line_start is None:
            at_ops.append(model.AtFileOp(operation="Read", path=path_str))
            formatted_blocks.append(
                f"Note: {path_str} is already in context and unchanged. "
                f"Use the {tools.READ} tool if you need to re-read it."
            )
            return

        # Build ReadTool args, passing offset/limit if line range specified
        read_kwargs: dict[str, object] = {"file_path": path_str}
        if ref.line_start is not None:
            read_kwargs["offset"] = ref.line_start
        if ref.line_end is not None and ref.line_start is not None:
            read_kwargs["limit"] = ref.line_end - ref.line_start + 1
        args = ReadTool.ReadArguments(**read_kwargs)  # type: ignore[arg-type]
        tool_result = await ReadTool.call_with_args(args, tool_context)
        images = [part for part in tool_result.parts if isinstance(part, message.ImageURLPart)]

        tool_args = args.model_dump_json(exclude_none=True)
        formatted_blocks.append(
            f"""Called the {tools.READ} tool with the following input: {tool_args}
Result of calling the {tools.READ} tool:
{tool_result.output_text}
"""
        )
        at_ops.append(model.AtFileOp(operation="Read", path=path_str))
        if images:
            collected_images.extend(images)
            collected_image_paths.append(path_str)
    elif path.exists() and path.is_dir():
        quoted_path = shlex.quote(path_str)
        args = BashTool.BashArguments(command=f"ls {quoted_path}")
        tool_result = await BashTool.call_with_args(args, tool_context)

        tool_args = args.model_dump_json(exclude_none=True)
        formatted_blocks.append(
            f"""Called the {tools.BASH} tool with the following input: {tool_args}
Result of calling the {tools.BASH} tool:
{tool_result.output_text}
"""
        )
        at_ops.append(model.AtFileOp(operation="List", path=path_str + "/"))

        # Discover memory files (AGENTS.md/CLAUDE.md) along the path from work_dir to this directory
        new_memories = discover_memory_files_near_paths(
            [path_str],
            work_dir=session.work_dir,
            is_memory_loaded=lambda p: _is_memory_loaded(session, p),
            mark_memory_loaded=lambda p: _mark_memory_loaded(session, p),
        )
        for memory in new_memories:
            formatted_blocks.append(format_memory_content(memory))
            discovered_memories.append(memory)


async def at_file_reader_attachment(
    session: Session,
) -> message.DeveloperMessage | None:
    """Parse @foo/bar references from the last user message and load them."""
    refs = get_at_patterns(session)
    if not refs:
        return None

    at_ops: list[model.AtFileOp] = []
    formatted_blocks: list[str] = []
    collected_images: list[message.ImageURLPart] = []
    collected_image_paths: list[str] = []
    discovered_memories: list[Memory] = []

    for ref in refs:
        await _load_at_file(
            session,
            ref,
            at_ops,
            formatted_blocks,
            collected_images,
            collected_image_paths,
            discovered_memories,
        )

    if len(formatted_blocks) == 0:
        return None

    at_files_str = "\n\n".join(formatted_blocks)
    ui_items: list[model.DeveloperUIItem] = [model.AtFileOpsUIItem(ops=at_ops)]
    if collected_image_paths:
        ui_items.append(model.AtFileImagesUIItem(paths=collected_image_paths))
    if discovered_memories:
        loaded_files = [model.MemoryFileLoaded(path=m.path) for m in discovered_memories]
        ui_items.append(model.MemoryLoadedUIItem(files=loaded_files))
    return message.DeveloperMessage(
        parts=message.parts_from_text_and_images(
            f"""<system-reminder>{at_files_str}\n</system-reminder>""",
            collected_images or None,
        ),
        ui_extra=model.DeveloperUIExtra(items=ui_items),
    )


def _compute_diff_snippet(old_content: str, new_content: str, path: str) -> str:
    """Compute a contextual diff snippet between old and new file content.

    Returns only the changed sections with surrounding context, rather than the
    full file content. This dramatically reduces context injection for large files
    with small changes.
    """
    old_lines = old_content.splitlines(keepends=True)
    new_lines = new_content.splitlines(keepends=True)

    diff_lines: list[str] = []
    for group in difflib.SequenceMatcher(None, old_lines, new_lines).get_grouped_opcodes(3):
        for tag, i1, i2, j1, j2 in group:
            if tag == "equal":
                for idx, line in enumerate(new_lines[j1:j2]):
                    line_no = j1 + idx + 1
                    diff_lines.append(f"  {line_no:>6}\t{line.rstrip()}")
            elif tag == "replace":
                for line in old_lines[i1:i2]:
                    diff_lines.append(f"       -\t{line.rstrip()}")
                for idx, line in enumerate(new_lines[j1:j2]):
                    line_no = j1 + idx + 1
                    diff_lines.append(f"  {line_no:>6}+\t{line.rstrip()}")
            elif tag == "delete":
                for line in old_lines[i1:i2]:
                    diff_lines.append(f"       -\t{line.rstrip()}")
            elif tag == "insert":
                for idx, line in enumerate(new_lines[j1:j2]):
                    line_no = j1 + idx + 1
                    diff_lines.append(f"  {line_no:>6}+\t{line.rstrip()}")
        diff_lines.append("  ------")

    return "\n".join(diff_lines).rstrip("\n -")


async def file_changed_externally_attachment(
    session: Session,
) -> message.DeveloperMessage | None:
    """Notify agent about user/linter changes, showing a diff snippet when possible."""
    changed_files: list[tuple[str, str, list[message.ImageURLPart] | None]] = []
    collected_images: list[message.ImageURLPart] = []
    if not session.file_tracker or len(session.file_tracker) == 0:
        return None

    # Snapshot keys to avoid dict-changed-size-during-iteration
    tracked_items = list(session.file_tracker.items())

    for path, status in tracked_items:
        try:
            current_mtime = Path(path).stat().st_mtime

            changed = False
            if status.content_sha256 is not None:
                current_sha256 = _compute_file_content_sha256(path)
                changed = current_sha256 is not None and current_sha256 != status.content_sha256
            else:
                changed = current_mtime != status.mtime

            if not changed:
                continue

            tool_context = ToolContext(
                file_tracker=session.file_tracker,
                todo_context=build_todo_context(session),
                session_id=session.id,
                work_dir=session.work_dir,
            )

            # Read the new content via ReadTool (this also updates file_tracker)
            tool_result = await ReadTool.call_with_args(
                ReadTool.ReadArguments(file_path=path),
                tool_context,
            )
            if tool_result.status != "success":
                continue

            images = [part for part in tool_result.parts if isinstance(part, message.ImageURLPart)]
            new_output = tool_result.output_text

            # Try to compute a diff snippet by finding the old ReadTool output in history
            old_output = _find_last_read_output(session, path)
            if old_output is not None:
                snippet = _compute_diff_snippet(old_output, new_output, path)
                if snippet:
                    changed_files.append((path, snippet, images or None))
                    if images:
                        collected_images.extend(images)
                    continue

            # Fallback: include full new content
            changed_files.append((path, new_output, images or None))
            if images:
                collected_images.extend(images)
        except (
            FileNotFoundError,
            IsADirectoryError,
            OSError,
            PermissionError,
            UnicodeDecodeError,
        ):
            continue

    if len(changed_files) > 0:
        changed_files_str = "\n\n".join(
            f"Note: {file_path} was modified, either by the user or by a linter. Don't tell the user this, since they are already aware. This change was intentional, so make sure to take it into account as you proceed (ie. don't revert it unless the user asks you to). Here are the relevant changes:\n\n{file_content}"
            for file_path, file_content, _ in changed_files
        )
        return message.DeveloperMessage(
            parts=message.parts_from_text_and_images(
                f"""<system-reminder>{changed_files_str}</system-reminder>""",
                collected_images or None,
            ),
            ui_extra=model.DeveloperUIExtra(
                items=[model.ExternalFileChangesUIItem(paths=[file_path for file_path, _, _ in changed_files])]
            ),
        )

    return None


def _find_last_read_output(session: Session, path: str) -> str | None:
    """Find the last ReadTool output for a given file path in conversation history.

    Searches backwards through DeveloperMessage (from @file reads) and
    ToolResultMessage (from explicit ReadTool calls) for output containing
    this file's path. Both use the same cat-n format, so diff is meaningful.
    """
    for item in reversed(session.conversation_history):
        if (
            isinstance(item, message.ToolResultMessage)
            and item.tool_name == tools.READ
            and path in item.output_text
        ):
            return item.output_text
        if isinstance(item, message.DeveloperMessage):
            # @file reads are wrapped in DeveloperMessage with the ReadTool output
            text = message.join_text_parts(item.parts)
            if path in text and "Result of calling the Read tool:" in text:
                # Extract the ReadTool output portion
                marker = "Result of calling the Read tool:\n"
                idx = text.find(marker)
                if idx >= 0:
                    return text[idx + len(marker) :].split("\n\nCalled the")[0].rstrip()
    return None


def _compute_file_content_sha256(path: str) -> str | None:
    """Compute SHA-256 for file content using the same decoding behavior as ReadTool."""

    try:
        suffix = Path(path).suffix.lower()
        if suffix in {".png", ".jpg", ".jpeg", ".gif", ".webp"}:
            with open(path, "rb") as f:
                return hashlib.sha256(f.read()).hexdigest()

        hasher = hashlib.sha256()
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                hasher.update(line.encode("utf-8"))
        return hasher.hexdigest()
    except (FileNotFoundError, IsADirectoryError, OSError, PermissionError, UnicodeDecodeError):
        return None


def get_last_user_message_image_paths(session: Session) -> list[str]:
    """Get image file paths from the last user message in conversation history."""
    for item in reversed(session.conversation_history):
        if isinstance(item, message.ToolResultMessage):
            return []
        if isinstance(item, message.UserMessage):
            paths: list[str] = []
            for part in item.parts:
                if isinstance(part, message.ImageFilePart):
                    paths.append(part.file_path)
            return paths
    return []


async def image_attachment(session: Session) -> message.DeveloperMessage | None:
    """Attach images from the last user message."""
    image_paths = get_last_user_message_image_paths(session)
    if not image_paths:
        return None

    return message.DeveloperMessage(
        parts=[],
        ui_extra=model.DeveloperUIExtra(items=[model.UserImagesUIItem(count=len(image_paths), paths=image_paths)]),
    )


async def skill_attachment(session: Session) -> message.DeveloperMessage | None:
    """Load skill content when user references skills with explicit skill syntax."""
    skill_names = get_skills_from_user_input(session)
    if not skill_names:
        return None

    skill_blocks: list[str] = []
    ui_items: list[model.DeveloperUIItem] = []

    for skill_name in skill_names:
        skill = get_skill(skill_name)
        if not skill:
            continue
        if not skill.skill_path.exists() or not skill.skill_path.is_file():
            continue
        skill_content = skill.skill_path.read_text(encoding="utf-8", errors="replace")
        if not skill_content:
            continue

        skill_path = str(skill.skill_path)
        existing = session.file_tracker.get(skill_path)
        session.file_tracker[skill_path] = model.FileStatus(
            mtime=skill.skill_path.stat().st_mtime,
            content_sha256=hash_text_sha256(skill_content),
            is_memory=existing.is_memory if existing else False,
        )

        skill_blocks.append(f"""The user activated the "{skill.name}" skill, prioritize this skill
<skill>
<name>{skill.name}</name>
<location>{skill.skill_path}</location>
<base_dir>{skill.base_dir}</base_dir>

{skill_content}
</skill>""")
        ui_items.append(model.SkillActivatedUIItem(name=skill.name))

    if not skill_blocks:
        return None

    content = f"<system-reminder>{chr(10).join(skill_blocks)}\n</system-reminder>"

    return message.DeveloperMessage(
        parts=message.text_parts_from_str(content),
        ui_extra=model.DeveloperUIExtra(items=ui_items),
    )


def _is_memory_loaded(session: Session, path: str) -> bool:
    """Check if a memory file has already been loaded or read unchanged."""
    status = session.file_tracker.get(path)
    if status is None:
        return False
    if status.is_memory:
        return True
    # Already tracked by ReadTool/@file - check if unchanged
    return _is_tracked_file_unchanged(session, path)


def _mark_memory_loaded(session: Session, path: str) -> None:
    """Mark a file as loaded memory in file_tracker."""
    try:
        mtime = Path(path).stat().st_mtime
    except (OSError, FileNotFoundError):
        mtime = 0.0
    try:
        content_sha256 = hash_text_sha256(Path(path).read_text(encoding="utf-8", errors="replace"))
    except (OSError, FileNotFoundError, PermissionError, UnicodeDecodeError):
        content_sha256 = None
    session.file_tracker[path] = model.FileStatus(mtime=mtime, content_sha256=content_sha256, is_memory=True)


def _truncate_memory_content(text: str, path: str) -> str:
    """Truncate memory file content to stay within per-file budget.

    Enforces both line count (AUTO_MEMORY_MAX_LINES) and byte size
    (MEMORY_MAX_BYTES_PER_FILE) limits. When truncated, appends a note
    so the model knows more content exists.
    """
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
        result += f"\n\n> This memory file was truncated ({MEMORY_MAX_BYTES_PER_FILE} byte limit). Use the {tools.READ} tool to view the complete file at: {path}"
    return result


def _count_memory_session_bytes(session: Session) -> int:
    """Count cumulative bytes of memory content already injected in this session."""
    total = 0
    for item in session.conversation_history:
        if isinstance(item, message.DeveloperMessage) and item.ui_extra:
            for ui_item in item.ui_extra.items:
                if isinstance(ui_item, model.MemoryLoadedUIItem):
                    # Estimate bytes from the text parts of this developer message
                    total += sum(len(p.text.encode("utf-8")) for p in item.parts if isinstance(p, message.TextPart))
                    break
    return total


async def memory_attachment(session: Session) -> message.DeveloperMessage | None:
    """CLAUDE.md AGENTS.md and per-project MEMORY.md with budget limits."""
    # Check session-level memory budget
    session_bytes = _count_memory_session_bytes(session)
    if session_bytes >= MEMORY_MAX_SESSION_BYTES:
        return None

    memory_paths = get_memory_paths(work_dir=session.work_dir)
    memories: list[Memory] = []
    remaining_budget = MEMORY_MAX_SESSION_BYTES - session_bytes

    for memory_path, instruction in memory_paths:
        path_str = str(memory_path)
        if memory_path.exists() and memory_path.is_file() and not _is_memory_loaded(session, path_str):
            try:
                text = memory_path.read_text(encoding="utf-8", errors="replace")
                text = _truncate_memory_content(text, path_str)
                text_bytes = len(text.encode("utf-8"))
                if text_bytes > remaining_budget:
                    # Would exceed session budget; truncate further or skip
                    if remaining_budget > 256:
                        text = text.encode("utf-8")[:remaining_budget].decode("utf-8", errors="ignore")
                        text += f"\n\n> Memory truncated due to session budget ({MEMORY_MAX_SESSION_BYTES} bytes total)."
                        text_bytes = len(text.encode("utf-8"))
                    else:
                        _mark_memory_loaded(session, path_str)
                        continue
                remaining_budget -= text_bytes
                _mark_memory_loaded(session, path_str)
                memories.append(Memory(path=path_str, instruction=instruction, content=text))
            except (PermissionError, UnicodeDecodeError, OSError):
                continue

    auto_mem = load_auto_memory(session.work_dir)
    auto_memory_hint = ""
    if auto_mem is not None:
        if not _is_memory_loaded(session, auto_mem.path):
            auto_mem_content = _truncate_memory_content(auto_mem.content, auto_mem.path)
            auto_mem_bytes = len(auto_mem_content.encode("utf-8"))
            if auto_mem_bytes <= remaining_budget:
                remaining_budget -= auto_mem_bytes
                _mark_memory_loaded(session, auto_mem.path)
                memories.append(Memory(path=auto_mem.path, instruction=auto_mem.instruction, content=auto_mem_content))
            else:
                _mark_memory_loaded(session, auto_mem.path)
    else:
        auto_memory_path = get_auto_memory_path(session.work_dir)
        path_str = str(auto_memory_path)
        if not _is_memory_loaded(session, path_str):
            _mark_memory_loaded(session, path_str)
            auto_memory_hint = f"\n\nNo auto memory file yet for this project. Create {auto_memory_path} when you need to persist memories."

    if memories or auto_memory_hint:
        loaded_files = [model.MemoryFileLoaded(path=memory.path) for memory in memories]
        ui_items: list[model.DeveloperUIItem] = [model.MemoryLoadedUIItem(files=loaded_files)] if loaded_files else []
        content_text = format_memories_attachment(memories, include_header=True) if memories else ""
        if auto_memory_hint:
            if content_text:
                content_text = content_text.replace("</system-reminder>", f"{auto_memory_hint}\n</system-reminder>")
            else:
                content_text = f"<system-reminder>{auto_memory_hint}\n</system-reminder>"
        return message.DeveloperMessage(
            parts=message.text_parts_from_str(content_text),
            attachment_position="prepend",
            ui_extra=model.DeveloperUIExtra(items=ui_items),
        )
    return None


async def last_path_memory_attachment(
    session: Session,
) -> message.DeveloperMessage | None:
    """Load CLAUDE.md/AGENTS.md from directories containing files in file_tracker.

    Uses session.file_tracker to detect accessed paths (works for both tool calls
    and @ file references). Checks is_memory flag to avoid duplicate loading.
    """
    if not session.file_tracker:
        return None

    paths = list(session.file_tracker.keys())
    memories = discover_memory_files_near_paths(
        paths,
        work_dir=session.work_dir,
        is_memory_loaded=lambda p: _is_memory_loaded(session, p),
        mark_memory_loaded=lambda p: _mark_memory_loaded(session, p),
    )

    if len(memories) > 0:
        loaded_files = [model.MemoryFileLoaded(path=memory.path) for memory in memories]
        return message.DeveloperMessage(
            parts=message.text_parts_from_str(format_memories_attachment(memories, include_header=False)),
            attachment_position="prepend",
            ui_extra=model.DeveloperUIExtra(items=[model.MemoryLoadedUIItem(files=loaded_files)]),
        )
    return None


def _count_assistant_turns_since(session: Session, predicate: str) -> tuple[int, int]:
    """Count assistant turns since last TodoWrite and since last todo_attachment.

    Returns (turns_since_write, turns_since_attachment).
    """
    turns_since_write = 0
    turns_since_attachment = 0
    found_write = False
    found_attachment = False

    for item in reversed(session.conversation_history):
        if isinstance(item, message.AssistantMessage):
            if not found_write:
                turns_since_write += 1
            if not found_attachment:
                turns_since_attachment += 1

        # Check for TodoWrite tool call in assistant messages
        if not found_write and isinstance(item, message.ToolResultMessage) and item.tool_name == tools.TODO_WRITE:
            found_write = True

        # Check for previous todo_attachment in developer messages
        if not found_attachment and isinstance(item, message.DeveloperMessage) and item.ui_extra:
            for ui_item in item.ui_extra.items:
                if isinstance(ui_item, model.TodoAttachmentUIItem):
                    found_attachment = True
                    break

        if found_write and found_attachment:
            break

    return turns_since_write, turns_since_attachment


async def todo_attachment(session: Session) -> message.DeveloperMessage | None:
    """Periodically attach a todo nudge if TodoWrite hasn't been used recently."""
    if not session.todos and not session.conversation_history:
        return None

    turns_since_write, turns_since_attachment = _count_assistant_turns_since(session, tools.TODO_WRITE)

    if turns_since_write < TODO_ATTACHMENT_TURNS_SINCE_WRITE:
        return None
    if turns_since_attachment < TODO_ATTACHMENT_TURNS_BETWEEN:
        return None

    todo_str = ""
    if session.todos:
        todo_items = "\n".join(f"{i + 1}. [{t.status}] {t.content}" for i, t in enumerate(session.todos))
        todo_str = f"\n\nHere are the existing contents of your todo list:\n\n[{todo_items}]"

    content = (
        "The TodoWrite tool hasn't been used recently. If you're working on tasks that would benefit "
        "from tracking progress, consider using the TodoWrite tool to track progress. Also consider "
        "cleaning up the todo list if it has become stale and no longer matches what you are working on. "
        "Only use it if it's relevant to the current work. This is just a gentle reminder - ignore if "
        "not applicable. Make sure that you NEVER mention this reminder to the user"
        f"{todo_str}"
    )

    reason: model.TodoAttachmentUIItem = model.TodoAttachmentUIItem(
        reason="not_used_recently" if session.todos else "empty"
    )

    return message.DeveloperMessage(
        parts=message.text_parts_from_str(f"<system-reminder>{content}\n</system-reminder>"),
        ui_extra=model.DeveloperUIExtra(items=[reason]),
    )


type Attachment = Callable[[Session], Awaitable[message.DeveloperMessage | None]]

# Attachments that mutate file_tracker or depend on another attachment's side effects
# must run sequentially. In particular:
# - at_file_reader_attachment writes to file_tracker via ReadTool
# - file_changed_externally_attachment iterates file_tracker (dict iteration safety)
# - last_path_memory_attachment reads file_tracker populated by at_file_reader_attachment
# These form a sequential phase. Others (memory_attachment, image_attachment,
# skill_attachment, todo_attachment) are independent and safe to parallelize.
_SEQUENTIAL_ATTACHMENTS: frozenset[str] = frozenset({
    "at_file_reader_attachment",
    "file_changed_externally_attachment",
    "last_path_memory_attachment",
})


async def collect_attachments(
    session: Session,
    attachments: Sequence[Attachment],
) -> list[message.DeveloperMessage]:
    """Collect attachments with error isolation and safe ordering.

    Attachments that share mutable state (file_tracker) run sequentially first.
    Independent attachments run in parallel afterward. Each attachment is wrapped
    in a try/except so one failure doesn't block others.
    """

    async def _safe_call(attachment: Attachment) -> message.DeveloperMessage | None:
        try:
            return await attachment(session)
        except Exception:
            name = getattr(attachment, "__name__", repr(attachment))
            logger.warning("Attachment %s failed", name, exc_info=True)
            return None

    sequential: list[Attachment] = []
    parallel: list[Attachment] = []
    for r in attachments:
        name = getattr(r, "__name__", "")
        if name in _SEQUENTIAL_ATTACHMENTS:
            sequential.append(r)
        else:
            parallel.append(r)

    results: list[message.DeveloperMessage | None] = []

    # Phase 1: sequential attachments (order-dependent, mutate file_tracker)
    for r in sequential:
        results.append(await _safe_call(r))

    # Phase 2: independent attachments in parallel
    if parallel:
        parallel_results = await asyncio.gather(*[_safe_call(r) for r in parallel])
        results.extend(parallel_results)

    return [r for r in results if r is not None]
