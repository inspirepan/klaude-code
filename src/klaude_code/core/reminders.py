import hashlib
import re
import shlex
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel

from klaude_code import const
from klaude_code.core.tool import BashTool, ReadTool, reset_tool_context, set_tool_context_from_session
from klaude_code.core.tool.file._utils import hash_text_sha256
from klaude_code.protocol import model, tools
from klaude_code.session import Session
from klaude_code.skill import get_skill

type Reminder = Callable[[Session], Awaitable[model.DeveloperMessageItem | None]]


# Match @ preceded by whitespace, start of line, or → (ReadTool line number arrow)
AT_FILE_PATTERN = re.compile(r'(?:(?<!\S)|(?<=\u2192))@("(?P<quoted>[^\"]+)"|(?P<plain>\S+))')

# Match $skill or ¥skill at the beginning of the first line
SKILL_PATTERN = re.compile(r"^[$¥](?P<skill>\S+)")


def get_last_new_user_input(session: Session) -> str | None:
    """Get last user input & developer message (CLAUDE.md) from conversation history. if there's a tool result after user input, return None"""
    result: list[str] = []
    for item in reversed(session.conversation_history):
        if isinstance(item, model.ToolResultItem):
            return None
        if isinstance(item, model.UserMessageItem):
            result.append(item.content or "")
            break
        if isinstance(item, model.DeveloperMessageItem):
            result.append(item.content or "")
    return "\n\n".join(result)


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
        if isinstance(item, model.ToolResultItem):
            break

        if isinstance(item, model.UserMessageItem):
            content = item.content or ""
            for path_str in _extract_at_patterns(content):
                patterns.append(AtPatternSource(pattern=path_str, mentioned_in=None))
            break

        if isinstance(item, model.DeveloperMessageItem) and item.memory_mentioned:
            for memory_path, mentioned_patterns in item.memory_mentioned.items():
                for pattern in mentioned_patterns:
                    patterns.append(AtPatternSource(pattern=pattern, mentioned_in=memory_path))
    return patterns


def get_skill_from_user_input(session: Session) -> str | None:
    """Get $skill reference from the first line of last user input."""
    for item in reversed(session.conversation_history):
        if isinstance(item, model.ToolResultItem):
            return None
        if isinstance(item, model.UserMessageItem):
            content = item.content or ""
            first_line = content.split("\n", 1)[0]
            m = SKILL_PATTERN.match(first_line)
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
    at_files: dict[str, model.AtPatternParseResult],
    collected_images: list[model.ImageURLPart],
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

    context_token = set_tool_context_from_session(session)
    try:
        if path.exists() and path.is_file():
            if _is_tracked_file_unchanged(session, path_str):
                return
            args = ReadTool.ReadArguments(file_path=path_str)
            tool_result = await ReadTool.call_with_args(args)
            at_files[path_str] = model.AtPatternParseResult(
                path=path_str,
                tool_name=tools.READ,
                result=tool_result.output or "",
                tool_args=args.model_dump_json(exclude_none=True),
                operation="Read",
                images=tool_result.images,
                mentioned_in=mentioned_in,
            )
            if tool_result.images:
                collected_images.extend(tool_result.images)

            # Recursively parse @ references from ReadTool output
            output = tool_result.output or ""
            if "@" in output:
                for match in AT_FILE_PATTERN.finditer(output):
                    nested = match.group("quoted") or match.group("plain")
                    if nested:
                        await _load_at_file_recursive(
                            session,
                            nested,
                            at_files,
                            collected_images,
                            visited,
                            base_dir=path.parent,
                            mentioned_in=path_str,
                        )
        elif path.exists() and path.is_dir():
            quoted_path = shlex.quote(path_str)
            args = BashTool.BashArguments(command=f"ls {quoted_path}")
            tool_result = await BashTool.call_with_args(args)
            at_files[path_str] = model.AtPatternParseResult(
                path=path_str + "/",
                tool_name=tools.BASH,
                result=tool_result.output or "",
                tool_args=args.model_dump_json(exclude_none=True),
                operation="List",
            )
    finally:
        reset_tool_context(context_token)


async def at_file_reader_reminder(
    session: Session,
) -> model.DeveloperMessageItem | None:
    """Parse @foo/bar to read, with recursive loading of nested @ references"""
    at_pattern_sources = get_at_patterns_with_source(session)
    if not at_pattern_sources:
        return None

    at_files: dict[str, model.AtPatternParseResult] = {}  # path -> content
    collected_images: list[model.ImageURLPart] = []
    visited: set[str] = set()

    for source in at_pattern_sources:
        await _load_at_file_recursive(
            session,
            source.pattern,
            at_files,
            collected_images,
            visited,
            mentioned_in=source.mentioned_in,
        )

    if len(at_files) == 0:
        return None

    at_files_str = "\n\n".join(
        [
            f"""Called the {result.tool_name} tool with the following input: {result.tool_args}
Result of calling the {result.tool_name} tool:
{result.result}
"""
            for result in at_files.values()
        ]
    )
    return model.DeveloperMessageItem(
        content=f"""<system-reminder>{at_files_str}\n</system-reminder>""",
        at_files=list(at_files.values()),
        images=collected_images or None,
    )


async def empty_todo_reminder(session: Session) -> model.DeveloperMessageItem | None:
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
        session.need_todo_empty_cooldown_counter = 3
        return model.DeveloperMessageItem(
            content="""<system-reminder>This is a reminder that your todo list is currently empty. DO NOT mention this to the user explicitly because they are already aware. If you are working on tasks that would benefit from a todo list please use the TodoWrite tool to create one. If not, please feel free to ignore. Again do not mention this message to the user.</system-reminder>"""
        )

    if session.need_todo_empty_cooldown_counter > 0:
        session.need_todo_empty_cooldown_counter -= 1
    return None


async def todo_not_used_recently_reminder(
    session: Session,
) -> model.DeveloperMessageItem | None:
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
        if isinstance(item, model.ToolCallItem):
            if item.name in (tools.TODO_WRITE, tools.UPDATE_PLAN):
                break
            other_tool_call_count_before_last_todo += 1
            if other_tool_call_count_before_last_todo >= const.TODO_REMINDER_TOOL_CALL_THRESHOLD:
                break

    not_used_recently = other_tool_call_count_before_last_todo >= const.TODO_REMINDER_TOOL_CALL_THRESHOLD

    if not not_used_recently:
        return None

    if session.need_todo_not_used_cooldown_counter == 0:
        session.need_todo_not_used_cooldown_counter = 3
        return model.DeveloperMessageItem(
            content=f"""<system-reminder>
The TodoWrite tool hasn't been used recently. If you're working on tasks that would benefit from tracking progress, consider using the TodoWrite tool to track progress. Also consider cleaning up the todo list if has become stale and no longer matches what you are working on. Only use it if it's relevant to the current work. This is just a gentle reminder - ignore if not applicable.


Here are the existing contents of your todo list:

{model.todo_list_str(session.todos)}</system-reminder>""",
            todo_use=True,
        )

    if session.need_todo_not_used_cooldown_counter > 0:
        session.need_todo_not_used_cooldown_counter -= 1
    return None


async def file_changed_externally_reminder(
    session: Session,
) -> model.DeveloperMessageItem | None:
    """Remind agent about user/linter' changes to the files in FileTracker, provding the newest content of the file."""
    changed_files: list[tuple[str, str, list[model.ImageURLPart] | None]] = []
    collected_images: list[model.ImageURLPart] = []
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
                    context_token = set_tool_context_from_session(session)
                    try:
                        tool_result = await ReadTool.call_with_args(
                            ReadTool.ReadArguments(file_path=path)
                        )  # This tool will update file tracker
                        if tool_result.status == "success":
                            changed_files.append((path, tool_result.output or "", tool_result.images))
                            if tool_result.images:
                                collected_images.extend(tool_result.images)
                    finally:
                        reset_tool_context(context_token)
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
        return model.DeveloperMessageItem(
            content=f"""<system-reminder>{changed_files_str}""",
            external_file_changes=[file_path for file_path, _, _ in changed_files],
            images=collected_images or None,
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


def get_memory_paths() -> list[tuple[Path, str]]:
    return [
        (
            Path.home() / ".claude" / "CLAUDE.md",
            "user's private global instructions for all projects",
        ),
        (
            Path.home() / ".codex" / "AGENTS.md",
            "user's private global instructions for all projects",
        ),
        (Path.cwd() / "AGENTS.md", "project instructions, checked into the codebase"),
        (Path.cwd() / "CLAUDE.md", "project instructions, checked into the codebase"),
        (Path.cwd() / ".claude" / "CLAUDE.md", "project instructions, checked into the codebase"),
    ]


class Memory(BaseModel):
    path: str
    instruction: str
    content: str


def get_last_user_message_image_count(session: Session) -> int:
    """Get image count from the last user message in conversation history."""
    for item in reversed(session.conversation_history):
        if isinstance(item, model.ToolResultItem):
            return 0
        if isinstance(item, model.UserMessageItem):
            return len(item.images) if item.images else 0
    return 0


async def image_reminder(session: Session) -> model.DeveloperMessageItem | None:
    """Remind agent about images attached by user in the last message."""
    image_count = get_last_user_message_image_count(session)
    if image_count == 0:
        return None

    return model.DeveloperMessageItem(
        content=f"<system-reminder>User attached {image_count} image{'s' if image_count > 1 else ''} in their message. Make sure to analyze and reference these images as needed.</system-reminder>",
        user_image_count=image_count,
    )


async def skill_reminder(session: Session) -> model.DeveloperMessageItem | None:
    """Load skill content when user references a skill with $skill syntax."""
    skill_name = get_skill_from_user_input(session)
    if not skill_name:
        return None

    # Get the skill from skill module
    skill = get_skill(skill_name)
    if not skill:
        return None

    # Get base directory from skill_path
    base_dir = str(skill.skill_path.parent) if skill.skill_path else "unknown"

    content = f"""<system-reminder>The user activated the "{skill.name}" skill. Here is the skill content:

<skill>
<name>{skill.name}</name>
<base_dir>{base_dir}</base_dir>

{skill.to_prompt()}
</skill>
</system-reminder>"""

    return model.DeveloperMessageItem(
        content=content,
        skill_name=skill.name,
    )


def _is_memory_loaded(session: Session, path: str) -> bool:
    """Check if a memory file has already been loaded (tracked with is_memory=True)."""
    status = session.file_tracker.get(path)
    return status is not None and status.is_memory


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


async def memory_reminder(session: Session) -> model.DeveloperMessageItem | None:
    """CLAUDE.md AGENTS.md"""
    memory_paths = get_memory_paths()
    memories: list[Memory] = []
    for memory_path, instruction in memory_paths:
        path_str = str(memory_path)
        if memory_path.exists() and memory_path.is_file() and not _is_memory_loaded(session, path_str):
            try:
                text = memory_path.read_text()
                _mark_memory_loaded(session, path_str)
                memories.append(Memory(path=path_str, instruction=instruction, content=text))
            except (PermissionError, UnicodeDecodeError, OSError):
                continue
    if len(memories) > 0:
        memories_str = "\n\n".join(
            [f"Contents of {memory.path} ({memory.instruction}):\n\n{memory.content}" for memory in memories]
        )
        # Build memory_mentioned: extract @ patterns from each memory's content
        memory_mentioned: dict[str, list[str]] = {}
        for memory in memories:
            patterns = _extract_at_patterns(memory.content)
            if patterns:
                memory_mentioned[memory.path] = patterns

        return model.DeveloperMessageItem(
            content=f"""<system-reminder>As you answer the user's questions, you can use the following context:

# claudeMd
Codebase and user instructions are shown below. Be sure to adhere to these instructions. IMPORTANT: These instructions OVERRIDE any default behavior and you MUST follow them exactly as written.
{memories_str}

#important-instruction-reminders
Do what has been asked; nothing more, nothing less.
NEVER create files unless they're absolutely necessary for achieving your goal.
ALWAYS prefer editing an existing file to creating a new one.
NEVER proactively create documentation files (*.md) or README files. Only create documentation files if explicitly requested by the User.

IMPORTANT: this context may or may not be relevant to your tasks. You should not respond to this context unless it is highly relevant to your task.
</system-reminder>""",
            memory_paths=[memory.path for memory in memories],
            memory_mentioned=memory_mentioned or None,
        )
    return None


MEMORY_FILE_NAMES = ["CLAUDE.md", "AGENTS.md", "AGENT.md"]


async def last_path_memory_reminder(
    session: Session,
) -> model.DeveloperMessageItem | None:
    """Load CLAUDE.md/AGENTS.md from directories containing files in file_tracker.

    Uses session.file_tracker to detect accessed paths (works for both tool calls
    and @ file references). Checks is_memory flag to avoid duplicate loading.
    """
    if not session.file_tracker:
        return None

    paths = list(session.file_tracker.keys())
    memories: list[Memory] = []

    cwd = Path.cwd().resolve()
    seen_memory_files: set[str] = set()

    for p_str in paths:
        p = Path(p_str)
        full = (cwd / p).resolve() if not p.is_absolute() else p.resolve()
        try:
            _ = full.relative_to(cwd)
        except ValueError:
            # Not under cwd; skip
            continue

        # Determine the deepest directory to scan (file parent or directory itself)
        deepest_dir = full if full.is_dir() else full.parent

        # Iterate each directory level from cwd to deepest_dir
        try:
            rel_parts = deepest_dir.relative_to(cwd).parts
        except ValueError:
            # Shouldn't happen due to check above, but guard anyway
            continue

        current_dir = cwd
        for part in rel_parts:
            current_dir = current_dir / part
            for fname in MEMORY_FILE_NAMES:
                mem_path = current_dir / fname
                mem_path_str = str(mem_path)
                if mem_path_str in seen_memory_files or _is_memory_loaded(session, mem_path_str):
                    continue
                if mem_path.exists() and mem_path.is_file():
                    try:
                        text = mem_path.read_text()
                    except (PermissionError, UnicodeDecodeError, OSError):
                        continue
                    _mark_memory_loaded(session, mem_path_str)
                    seen_memory_files.add(mem_path_str)
                    memories.append(
                        Memory(
                            path=mem_path_str,
                            instruction="project instructions, discovered near last accessed path",
                            content=text,
                        )
                    )

    if len(memories) > 0:
        memories_str = "\n\n".join(
            [f"Contents of {memory.path} ({memory.instruction}):\n\n{memory.content}" for memory in memories]
        )
        # Build memory_mentioned: extract @ patterns from each memory's content
        memory_mentioned: dict[str, list[str]] = {}
        for memory in memories:
            patterns = _extract_at_patterns(memory.content)
            if patterns:
                memory_mentioned[memory.path] = patterns

        return model.DeveloperMessageItem(
            content=f"""<system-reminder>{memories_str}
</system-reminder>""",
            memory_paths=[memory.path for memory in memories],
            memory_mentioned=memory_mentioned or None,
        )


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


def load_agent_reminders(
    model_name: str, sub_agent_type: str | None = None, *, vanilla: bool = False
) -> list[Reminder]:
    """Get reminders for an agent based on model and agent type.

    Args:
        model_name: The model name.
        sub_agent_type: If None, returns main agent reminders. Otherwise returns sub-agent reminders.
        vanilla: If True, returns minimal vanilla reminders (ignores sub_agent_type).
    """
    if vanilla:
        return [at_file_reader_reminder]

    reminders: list[Reminder] = []

    # Only main agent (not sub-agent) gets todo reminders, and not for GPT-5
    if sub_agent_type is None and "gpt-5" not in model_name:
        reminders.append(empty_todo_reminder)
        reminders.append(todo_not_used_recently_reminder)

    reminders.extend(
        [
            memory_reminder,
            at_file_reader_reminder,
            last_path_memory_reminder,
            file_changed_externally_reminder,
            image_reminder,
            skill_reminder,
        ]
    )

    return reminders
