import hashlib
import re
import shlex
from dataclasses import dataclass
from pathlib import Path

from klaude_code.const import REMINDER_COOLDOWN_TURNS, TODO_REMINDER_TOOL_CALL_THRESHOLD
from klaude_code.core.memory import (
    Memory,
    discover_memory_files_near_paths,
    format_memories_reminder,
    get_memory_paths,
)
from klaude_code.core.tool import BashTool, ReadTool, build_todo_context
from klaude_code.core.tool.context import ToolContext
from klaude_code.core.tool.file._utils import hash_text_sha256
from klaude_code.protocol import message, model, tools
from klaude_code.session import Session
from klaude_code.skill import get_skill

# Match @ preceded by whitespace, start of line, or → (ReadTool line number arrow)
AT_FILE_PATTERN = re.compile(r'(?:(?<!\S)|(?<=\u2192))@("(?P<quoted>[^\"]+)"|(?P<plain>\S+))')

# Match $skill or ¥skill inline (at start of line or after whitespace)
SKILL_PATTERN = re.compile(r"(?:^|\s)[$¥](?P<skill>\S+)")


@dataclass
class AtPatternSource:
    """Represents an @ pattern with its source file (if from a memory file)."""

    pattern: str
    mentioned_in: str | None = None


def _extract_at_patterns(content: str) -> list[str]:
    """Extract @ patterns from content."""
    patterns: list[str] = []
    if "@" in content:
        for match in AT_FILE_PATTERN.finditer(content):
            path_str = match.group("quoted") or match.group("plain")
            if path_str:
                patterns.append(path_str)
    return patterns


def get_at_patterns_with_source(session: Session) -> list[AtPatternSource]:
    """Get @ patterns from last user input and developer messages, preserving source info."""
    patterns: list[AtPatternSource] = []

    for item in reversed(session.conversation_history):
        if isinstance(item, message.ToolResultMessage):
            break

        if isinstance(item, message.UserMessage):
            content = message.join_text_parts(item.parts)
            for path_str in _extract_at_patterns(content):
                patterns.append(AtPatternSource(pattern=path_str, mentioned_in=None))
            break

        if isinstance(item, message.DeveloperMessage) and item.ui_extra:
            for ui_item in item.ui_extra.items:
                if not isinstance(ui_item, model.MemoryLoadedUIItem):
                    continue
                for mem in ui_item.files:
                    for pattern in mem.mentioned_patterns:
                        patterns.append(AtPatternSource(pattern=pattern, mentioned_in=mem.path))
    return patterns


def get_skill_from_user_input(session: Session) -> str | None:
    """Get $skill reference from last user input (first match wins)."""
    for item in reversed(session.conversation_history):
        if isinstance(item, message.ToolResultMessage):
            return None
        if isinstance(item, message.UserMessage):
            content = message.join_text_parts(item.parts)
            m = SKILL_PATTERN.search(content)
            if m:
                return m.group("skill")
            return None
    return None


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


async def _load_at_file_recursive(
    session: Session,
    pattern: str,
    at_ops: list[model.AtFileOp],
    formatted_blocks: list[str],
    collected_images: list[message.ImageURLPart],
    collected_image_paths: list[str],
    visited: set[str],
    base_dir: Path | None = None,
    mentioned_in: str | None = None,
) -> None:
    """Recursively load @ file references."""
    path = (base_dir / pattern).resolve() if base_dir else Path(pattern).resolve()
    path_str = str(path)

    if path_str in visited:
        return
    visited.add(path_str)

    tool_context = ToolContext(
        file_tracker=session.file_tracker,
        todo_context=build_todo_context(session),
        session_id=session.id,
    )

    if path.exists() and path.is_file():
        if _is_tracked_file_unchanged(session, path_str):
            return
        args = ReadTool.ReadArguments(file_path=path_str)
        tool_result = await ReadTool.call_with_args(args, tool_context)
        images = [part for part in tool_result.parts if isinstance(part, message.ImageURLPart)]

        tool_args = args.model_dump_json(exclude_none=True)
        formatted_blocks.append(
            f"""Called the {tools.READ} tool with the following input: {tool_args}
Result of calling the {tools.READ} tool:
{tool_result.output_text}
"""
        )
        at_ops.append(model.AtFileOp(operation="Read", path=path_str, mentioned_in=mentioned_in))
        if images:
            collected_images.extend(images)
            collected_image_paths.append(path_str)

        # Recursively parse @ references from ReadTool output
        output = tool_result.output_text
        if "@" in output:
            for match in AT_FILE_PATTERN.finditer(output):
                nested = match.group("quoted") or match.group("plain")
                if nested:
                    await _load_at_file_recursive(
                        session,
                        nested,
                        at_ops,
                        formatted_blocks,
                        collected_images,
                        collected_image_paths,
                        visited,
                        base_dir=path.parent,
                        mentioned_in=path_str,
                    )
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
        at_ops.append(model.AtFileOp(operation="List", path=path_str + "/", mentioned_in=mentioned_in))


async def at_file_reader_reminder(
    session: Session,
) -> message.DeveloperMessage | None:
    """Parse @foo/bar to read, with recursive loading of nested @ references"""
    at_pattern_sources = get_at_patterns_with_source(session)
    if not at_pattern_sources:
        return None

    at_ops: list[model.AtFileOp] = []
    formatted_blocks: list[str] = []
    collected_images: list[message.ImageURLPart] = []
    collected_image_paths: list[str] = []
    visited: set[str] = set()

    for source in at_pattern_sources:
        await _load_at_file_recursive(
            session,
            source.pattern,
            at_ops,
            formatted_blocks,
            collected_images,
            collected_image_paths,
            visited,
            mentioned_in=source.mentioned_in,
        )

    if len(formatted_blocks) == 0:
        return None

    at_files_str = "\n\n".join(formatted_blocks)
    ui_items: list[model.DeveloperUIItem] = [model.AtFileOpsUIItem(ops=at_ops)]
    if collected_image_paths:
        ui_items.append(model.AtFileImagesUIItem(paths=collected_image_paths))
    return message.DeveloperMessage(
        parts=message.parts_from_text_and_images(
            f"""<system-reminder>{at_files_str}\n</system-reminder>""",
            collected_images or None,
        ),
        ui_extra=model.DeveloperUIExtra(items=ui_items),
    )


async def empty_todo_reminder(session: Session) -> message.DeveloperMessage | None:
    """Remind agent to use TodoWrite tool when todos are empty/all completed.

    Behavior:
    - First time in empty state (counter == 0): trigger reminder and set cooldown (e.g., 3).
    - While remaining in empty state with counter > 0: decrement each turn, no reminder.
    - Do not decrement/reset while todos are non-empty (cooldown only counts during empty state).
    """

    empty_or_all_done = (not session.todos) or all(todo.status == "completed" for todo in session.todos)

    # Only count down and possibly trigger when empty/all-done
    if not empty_or_all_done:
        return None

    if session.need_todo_empty_cooldown_counter == 0:
        session.need_todo_empty_cooldown_counter = REMINDER_COOLDOWN_TURNS
        return message.DeveloperMessage(
            parts=message.text_parts_from_str(
                "<system-reminder>This is a reminder that your todo list is currently empty. DO NOT mention this to the user explicitly because they are already aware. If you are working on tasks that would benefit from a todo list please use the TodoWrite tool to create one. If not, please feel free to ignore. Again do not mention this message to the user.</system-reminder>"
            )
        )

    if session.need_todo_empty_cooldown_counter > 0:
        session.need_todo_empty_cooldown_counter -= 1
    return None


async def todo_not_used_recently_reminder(
    session: Session,
) -> message.DeveloperMessage | None:
    """Remind agent to use TodoWrite tool if it hasn't been used recently (>=10 other tool calls), with cooldown.

    Cooldown behavior:
    - When condition becomes active (>=10 non-todo tool calls since last TodoWrite) and counter == 0: trigger reminder, set counter = 3.
    - While condition remains active and counter > 0: decrement each turn, do not remind.
    - When condition not active: do nothing to the counter (no decrement), and do not remind.
    """

    if not session.todos:
        return None

    # If all todos completed, skip reminder entirely
    if all(todo.status == "completed" for todo in session.todos):
        return None

    # Count non-todo tool calls since the last TodoWrite
    other_tool_call_count_before_last_todo = 0
    for item in reversed(session.conversation_history):
        if not isinstance(item, message.AssistantMessage):
            continue
        for part in reversed(item.parts):
            if not isinstance(part, message.ToolCallPart):
                continue
            if part.tool_name in (tools.TODO_WRITE, tools.UPDATE_PLAN):
                other_tool_call_count_before_last_todo = 0
                break
            other_tool_call_count_before_last_todo += 1
            if other_tool_call_count_before_last_todo >= TODO_REMINDER_TOOL_CALL_THRESHOLD:
                break
        if other_tool_call_count_before_last_todo == 0:
            break

    not_used_recently = other_tool_call_count_before_last_todo >= TODO_REMINDER_TOOL_CALL_THRESHOLD

    if not not_used_recently:
        return None

    if session.need_todo_not_used_cooldown_counter == 0:
        session.need_todo_not_used_cooldown_counter = REMINDER_COOLDOWN_TURNS
        return message.DeveloperMessage(
            parts=message.text_parts_from_str(
                f"""<system-reminder>
The TodoWrite tool hasn't been used recently. If you're working on tasks that would benefit from tracking progress, consider using the TodoWrite tool to track progress. Also consider cleaning up the todo list if has become stale and no longer matches what you are working on. Only use it if it's relevant to the current work. This is just a gentle reminder - ignore if not applicable.


Here are the existing contents of your todo list:

{model.todo_list_str(session.todos)}</system-reminder>"""
            ),
            ui_extra=model.DeveloperUIExtra(items=[model.TodoReminderUIItem(reason="not_used_recently")]),
        )

    if session.need_todo_not_used_cooldown_counter > 0:
        session.need_todo_not_used_cooldown_counter -= 1
    return None


async def file_changed_externally_reminder(
    session: Session,
) -> message.DeveloperMessage | None:
    """Remind agent about user/linter' changes to the files in FileTracker, provding the newest content of the file."""
    changed_files: list[tuple[str, str, list[message.ImageURLPart] | None]] = []
    collected_images: list[message.ImageURLPart] = []
    if session.file_tracker and len(session.file_tracker) > 0:
        for path, status in session.file_tracker.items():
            try:
                current_mtime = Path(path).stat().st_mtime

                changed = False
                if status.content_sha256 is not None:
                    current_sha256 = _compute_file_content_sha256(path)
                    changed = current_sha256 is not None and current_sha256 != status.content_sha256
                else:
                    # Backward-compat: old sessions only tracked mtime.
                    changed = current_mtime != status.mtime

                if changed:
                    tool_context = ToolContext(
                        file_tracker=session.file_tracker,
                        todo_context=build_todo_context(session),
                        session_id=session.id,
                    )
                    tool_result = await ReadTool.call_with_args(
                        ReadTool.ReadArguments(file_path=path),
                        tool_context,
                    )  # This tool will update file tracker
                    if tool_result.status == "success":
                        images = [part for part in tool_result.parts if isinstance(part, message.ImageURLPart)]
                        changed_files.append((path, tool_result.output_text, images or None))
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
            [
                f"Note: {file_path} was modified, either by the user or by a linter. Don't tell the user this, since they are already aware. This change was intentional, so make sure to take it into account as you proceed (ie. don't revert it unless the user asks you to). So that you don't need to re-read the file, here's the result of running `cat -n` on a snippet of the edited file:\n\n{file_content}"
                ""
                for file_path, file_content, _ in changed_files
            ]
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


async def image_reminder(session: Session) -> message.DeveloperMessage | None:
    """Remind agent about images attached by user in the last message."""
    image_paths = get_last_user_message_image_paths(session)
    if not image_paths:
        return None

    return message.DeveloperMessage(
        parts=[],
        ui_extra=model.DeveloperUIExtra(items=[model.UserImagesUIItem(count=len(image_paths), paths=image_paths)]),
    )


async def skill_reminder(session: Session) -> message.DeveloperMessage | None:
    """Load skill content when user references a skill with $skill syntax."""
    skill_name = get_skill_from_user_input(session)
    if not skill_name:
        return None

    # Get the skill from skill module
    skill = get_skill(skill_name)
    if not skill:
        return None

    if not skill.skill_path.exists() or not skill.skill_path.is_file():
        return None

    tool_context = ToolContext(
        file_tracker=session.file_tracker,
        todo_context=build_todo_context(session),
        session_id=session.id,
    )
    args = ReadTool.ReadArguments(file_path=str(skill.skill_path))
    tool_result = await ReadTool.call_with_args(args, tool_context)

    tool_args = args.model_dump_json(exclude_none=True)
    skill_file_str = f"""Called the {tools.READ} tool with the following input: {tool_args}
Result of calling the {tools.READ} tool:
{tool_result.output_text}
"""

    base_dir = str(skill.base_dir)
    content = f"""<system-reminder>The user activated the "{skill.name}" skill.

<skill>
<name>{skill.name}</name>
<base_dir>{base_dir}</base_dir>
<location>{skill.skill_path}</location>

{skill_file_str}
</skill>
</system-reminder>"""

    return message.DeveloperMessage(
        parts=message.text_parts_from_str(content),
        ui_extra=model.DeveloperUIExtra(items=[model.SkillActivatedUIItem(name=skill.name)]),
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


async def memory_reminder(session: Session) -> message.DeveloperMessage | None:
    """CLAUDE.md AGENTS.md"""
    memory_paths = get_memory_paths(work_dir=session.work_dir)
    memories: list[Memory] = []
    for memory_path, instruction in memory_paths:
        path_str = str(memory_path)
        if memory_path.exists() and memory_path.is_file() and not _is_memory_loaded(session, path_str):
            try:
                text = memory_path.read_text(encoding="utf-8", errors="replace")
                _mark_memory_loaded(session, path_str)
                memories.append(Memory(path=path_str, instruction=instruction, content=text))
            except (PermissionError, UnicodeDecodeError, OSError):
                continue
    if len(memories) > 0:
        loaded_files = [
            model.MemoryFileLoaded(path=memory.path, mentioned_patterns=_extract_at_patterns(memory.content))
            for memory in memories
        ]
        return message.DeveloperMessage(
            parts=message.text_parts_from_str(format_memories_reminder(memories, include_header=True)),
            ui_extra=model.DeveloperUIExtra(items=[model.MemoryLoadedUIItem(files=loaded_files)]),
        )
    return None


async def last_path_memory_reminder(
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
        loaded_files = [
            model.MemoryFileLoaded(path=memory.path, mentioned_patterns=_extract_at_patterns(memory.content))
            for memory in memories
        ]
        return message.DeveloperMessage(
            parts=message.text_parts_from_str(format_memories_reminder(memories, include_header=False)),
            ui_extra=model.DeveloperUIExtra(items=[model.MemoryLoadedUIItem(files=loaded_files)]),
        )
    return None


ALL_REMINDERS = [
    empty_todo_reminder,
    todo_not_used_recently_reminder,
    file_changed_externally_reminder,
    memory_reminder,
    last_path_memory_reminder,
    at_file_reader_reminder,
    image_reminder,
    skill_reminder,
]
