import json
import re
from pathlib import Path
from typing import Awaitable, Callable

from pydantic import BaseModel

from codex_mini.core.tool.bash_tool import BashTool
from codex_mini.core.tool.read_tool import ReadTool
from codex_mini.core.tool.tool_context import current_session_var
from codex_mini.protocol import model, tools
from codex_mini.session import Session

type Reminder = Callable[[Session], Awaitable[model.DeveloperMessageItem | None]]


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


async def at_file_reader_reminder(session: Session) -> model.DeveloperMessageItem | None:
    """Parse @foo/bar to read"""
    last_user_input = get_last_new_user_input(session)
    if not last_user_input or "@" not in last_user_input.strip():
        return None

    at_patterns: list[str] = []

    for item in last_user_input.strip().split():
        if item.startswith("@") and len(item) > 1:
            at_patterns.append(item.lower().strip("@"))

    if len(at_patterns) == 0:
        return None

    at_files: dict[str, model.AtPatternParseResult] = {}  # path -> content
    collected_images: list[model.ImageURLPart] = []

    for pattern in at_patterns:
        path = Path(pattern).resolve()
        token = current_session_var.set(session)
        try:
            if path.exists() and path.is_file():
                args = ReadTool.ReadArguments(file_path=str(path))
                tool_result = await ReadTool.call_with_args(args)
                at_result = model.AtPatternParseResult(
                    path=str(path),
                    tool_name=tools.READ,
                    result=tool_result.output or "",
                    tool_args=args.model_dump_json(exclude_none=True),
                    operation="Read",
                    images=tool_result.images,
                )
                at_files[str(path)] = at_result
                if tool_result.images:
                    collected_images.extend(tool_result.images)
            elif path.exists() and path.is_dir():
                args = BashTool.BashArguments(command=f"ls {path}")
                tool_result = await BashTool.call_with_args(args)
                at_files[str(path)] = model.AtPatternParseResult(
                    path=str(path) + "/",
                    tool_name=tools.BASH,
                    result=tool_result.output or "",
                    tool_args=args.model_dump_json(exclude_none=True),
                    operation="List",
                )
        finally:
            current_session_var.reset(token)

    if len(at_files) == 0:
        return None

    at_files_str = "\n\n".join(
        [
            f"""Called the {result.tool_name} tool with the following input: {result.tool_args}
Result of calling the {result.tool_name} tool:
{result.result}"""
            for result in at_files.values()
        ]
    )
    return model.DeveloperMessageItem(
        content=f"""<system-reminder>{at_files_str}</system-reminder>""",
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


async def todo_not_used_recently_reminder(session: Session) -> model.DeveloperMessageItem | None:
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
    other_tool_call_count_befor_last_todo = 0
    for item in reversed(session.conversation_history):
        if isinstance(item, model.ToolCallItem):
            if item.name in (tools.TODO_WRITE, tools.UPDATE_PLAN):
                break
            other_tool_call_count_befor_last_todo += 1
            if other_tool_call_count_befor_last_todo >= 10:
                break

    not_used_recently = other_tool_call_count_befor_last_todo >= 10

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


async def file_changed_externally_reminder(session: Session) -> model.DeveloperMessageItem | None:
    """Remind agent about user/linter' changes to the files in FileTracker, provding the newest content of the file."""
    changed_files: list[tuple[str, str, list[model.ImageURLPart] | None]] = []
    collected_images: list[model.ImageURLPart] = []
    if session.file_tracker and len(session.file_tracker) > 0:
        for path, mtime in session.file_tracker.items():
            try:
                if Path(path).stat().st_mtime > mtime:
                    token = current_session_var.set(session)
                    try:
                        tool_result = await ReadTool.call_with_args(
                            ReadTool.ReadArguments(file_path=path)
                        )  # This tool will update file tracker
                        if tool_result.status == "success":
                            changed_files.append((path, tool_result.output or "", tool_result.images))
                            if tool_result.images:
                                collected_images.extend(tool_result.images)
                    finally:
                        current_session_var.reset(token)
            except (FileNotFoundError, IsADirectoryError, OSError, PermissionError, UnicodeDecodeError):
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


def get_memory_paths() -> list[tuple[Path, str]]:
    return [
        (Path.home() / ".claude" / "CLAUDE.md", "user's private global instructions for all projects"),
        (Path.home() / ".codex" / "AGENTS.md", "user's private global instructions for all projects"),
        (Path.cwd() / "AGENTS.md", "project instructions, checked into the codebase"),
        (Path.cwd() / "AGENT.md", "project instructions, checked into the codebase"),
        (Path.cwd() / "CLAUDE.md", "project instructions, checked into the codebase"),
    ]


class Memory(BaseModel):
    path: str
    instruction: str
    content: str


async def memory_reminder(session: Session) -> model.DeveloperMessageItem | None:
    """CLAUDE.md AGENTS.md"""
    memory_paths = get_memory_paths()
    memories: list[Memory] = []
    for memory_path, instruction in memory_paths:
        if memory_path.exists() and memory_path.is_file() and str(memory_path) not in session.loaded_memory:
            try:
                text = memory_path.read_text()
                session.loaded_memory.append(str(memory_path))
                memories.append(Memory(path=str(memory_path), instruction=instruction, content=text))
            except (PermissionError, UnicodeDecodeError, OSError):
                continue
    if len(memories) > 0:
        memories_str = "\n\n".join(
            [f"Contents of {memory.path} ({memory.instruction}):\n\n{memory.content}" for memory in memories]
        )
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
        )
    return None


def get_last_turn_tool_call(session: Session) -> list[model.ToolCallItem]:
    tool_calls: list[model.ToolCallItem] = []
    for item in reversed(session.conversation_history):
        if isinstance(item, model.ToolCallItem):
            tool_calls.append(item)
        if isinstance(item, (model.ReasoningEncryptedItem, model.ReasoningTextItem, model.AssistantMessageItem)):
            break
    return tool_calls


MEMORY_FILE_NAMES = ["CLAUDE.md", "AGENTS.md", "AGENT.md"]


async def last_path_memory_reminder(session: Session) -> model.DeveloperMessageItem | None:
    """When last turn tool call entered a directory (or parent directory) with CLAUDE.md AGENTS.md"""
    tool_calls = get_last_turn_tool_call(session)
    if len(tool_calls) == 0:
        return None
    paths: list[str] = []
    for tool_call in tool_calls:
        if tool_call.name in (tools.READ, tools.EDIT, tools.MULTI_EDIT):
            try:
                json_dict = json.loads(tool_call.arguments)
                if path := json_dict.get("file_path", ""):
                    paths.append(path)
            except json.JSONDecodeError:
                continue
        elif tool_call.name == tools.BASH:
            # TODO: haiku check file path
            pass
    paths = list(set(paths))
    memories: list[Memory] = []
    if len(paths) == 0:
        return None

    cwd = Path.cwd().resolve()
    loaded_set: set[str] = set(session.loaded_memory)
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
                if mem_path_str in seen_memory_files or mem_path_str in loaded_set:
                    continue
                if mem_path.exists() and mem_path.is_file():
                    try:
                        text = mem_path.read_text()
                    except (PermissionError, UnicodeDecodeError, OSError):
                        continue
                    session.loaded_memory.append(mem_path_str)
                    loaded_set.add(mem_path_str)
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
        return model.DeveloperMessageItem(
            content=f"""<system-reminder>{memories_str}
</system-reminder>""",
            memory_paths=[memory.path for memory in memories],
        )


async def clipboard_image_reminder(session: Session) -> model.DeveloperMessageItem | None:
    """Parse [Image #N] and attach images from clipboard history."""
    last_user_input = get_last_new_user_input(session)
    if not last_user_input or "[Image #" not in last_user_input:
        return None

    image_map_file = Path.home() / ".config" / "codex-mini" / "clipboard" / "last_clipboard_images.json"
    if not image_map_file.exists():
        return None

    try:
        with open(image_map_file, "r") as f:
            image_map = json.load(f)
    except Exception:
        return None

    if not image_map:
        return None

    collected_images: list[model.ImageURLPart] = []
    found_images: list[str] = []  # To list in the text message

    # Find all tokens
    # Regex for [Image #(\d+)]
    matches = re.findall(r"\[Image #(\d+)\]", last_user_input)
    requested_tags = [f"[Image #{num}]" for num in matches]

    processed_paths: set[str] = set()

    attached_tags: list[str] = []

    for tag in requested_tags:
        if tag in image_map:
            path = image_map[tag]
            if path in processed_paths:
                continue

            token = current_session_var.set(session)
            try:
                # We use ReadTool to get the image object in the correct format
                # This assumes ReadTool handles image files correctly
                args = ReadTool.ReadArguments(file_path=path)
                tool_result = await ReadTool.call_with_args(args)
                if tool_result.images:
                    collected_images.extend(tool_result.images)
                    found_images.append(f"{tag}: {path}")
                    processed_paths.add(path)
                    attached_tags.append(tag)
            finally:
                current_session_var.reset(token)

    if not collected_images:
        return None

    msg = "\n".join(found_images)
    return model.DeveloperMessageItem(
        content=f"<system-reminder>Attached clipboard images:\n{msg}</system-reminder>",
        images=collected_images,
        clipboard_images=attached_tags,
    )


ALL_REMINDERS = [
    empty_todo_reminder,
    todo_not_used_recently_reminder,
    file_changed_externally_reminder,
    memory_reminder,
    last_path_memory_reminder,
    at_file_reader_reminder,
    clipboard_image_reminder,
]


def get_main_agent_reminders(vanilla: bool, model_name: str) -> list[Reminder]:
    if vanilla:
        return [at_file_reader_reminder, clipboard_image_reminder]

    reminders: list[Reminder] = []

    # For GPT-5, we do not show empty todo and todo not used recently reminders
    if "gpt-5" not in model_name:
        reminders.append(empty_todo_reminder)
        reminders.append(todo_not_used_recently_reminder)

    reminders.extend(
        [
            memory_reminder,
            last_path_memory_reminder,
            at_file_reader_reminder,
            clipboard_image_reminder,
            file_changed_externally_reminder,
        ]
    )

    return reminders


def get_sub_agent_reminders(vanilla: bool, model_name: str) -> list[Reminder]:
    if vanilla:
        return [at_file_reader_reminder, clipboard_image_reminder]

    reminders: list[Reminder] = []
    reminders.extend(
        [
            memory_reminder,
            last_path_memory_reminder,
            at_file_reader_reminder,
            clipboard_image_reminder,
            file_changed_externally_reminder,
        ]
    )

    return reminders
