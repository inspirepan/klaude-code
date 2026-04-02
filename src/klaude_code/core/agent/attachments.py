import asyncio
import difflib
import hashlib
import logging
import re
import shlex
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path
from typing import Literal

from klaude_code.core.agent.attachment_messages import (
    fmt_auto_memory_hint,
    fmt_dynamic_available_skills,
    fmt_file_already_in_context,
    fmt_file_changed_externally,
    fmt_memory_truncated,
    fmt_skill_block,
    fmt_todo_items,
    fmt_todo_nudge,
    fmt_tool_result,
)
from klaude_code.core.memory import (
    Memory,
    discover_memory_files_near_paths,
    format_memories_attachment,
    format_memory_content,
    get_auto_memory_path,
    get_memory_paths,
    load_auto_memory,
    truncate_memory_content,
)
from klaude_code.core.tool import BashTool, ReadTool, build_todo_context
from klaude_code.core.tool.context import ToolContext
from klaude_code.core.tool.file._utils import hash_text_sha256
from klaude_code.protocol import message, model, tools
from klaude_code.session import Session
from klaude_code.skill import get_skill, get_skill_loader
from klaude_code.skill.loader import Skill, SkillLoader, discover_skills_near_paths

logger = logging.getLogger(__name__)

# Match @ preceded by whitespace, start of line, or → (ReadTool line number arrow)
# Supports optional line range suffix: @file.txt#L10-20 or @file.txt#L10
AT_FILE_PATTERN = re.compile(r'(?:(?<!\S)|(?<=\u2192))@("(?P<quoted>[^\"]+)"|(?P<plain>\S+))')

# Memory budget limits (inspired by Claude Code's attachment system)
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
    skill_discovery_paths: list[str],
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
            formatted_blocks.append(fmt_file_already_in_context(path_str, tools.READ))
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
        formatted_blocks.append(fmt_tool_result(tools.READ, tool_args, tool_result.output_text))
        at_ops.append(model.AtFileOp(operation="Read", path=path_str))
        if images:
            collected_images.extend(images)
            collected_image_paths.append(path_str)
    elif path.exists() and path.is_dir():
        quoted_path = shlex.quote(path_str)
        args = BashTool.BashArguments(command=f"ls {quoted_path}")
        tool_result = await BashTool.call_with_args(args, tool_context)

        tool_args = args.model_dump_json(exclude_none=True)
        formatted_blocks.append(fmt_tool_result(tools.BASH, tool_args, tool_result.output_text))
        at_ops.append(model.AtFileOp(operation="List", path=path_str + "/"))
        _mark_directory_accessed(session, path_str)

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
        skill_discovery_paths.append(path_str)


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
    skill_discovery_paths: list[str] = []

    for ref in refs:
        await _load_at_file(
            session,
            ref,
            at_ops,
            formatted_blocks,
            collected_images,
            collected_image_paths,
            discovered_memories,
            skill_discovery_paths,
        )

    dynamic_skill_attachment = _build_dynamic_skill_listing_attachment(
        session,
        discover_skills_near_paths(skill_discovery_paths, work_dir=session.work_dir),
    )
    dynamic_skill_text = ""
    if dynamic_skill_attachment is not None:
        dynamic_skill_text = message.join_text_parts(dynamic_skill_attachment.parts)
        if dynamic_skill_text.startswith("<system-reminder>") and dynamic_skill_text.endswith("</system-reminder>"):
            dynamic_skill_text = dynamic_skill_text.removeprefix("<system-reminder>").removesuffix("</system-reminder>")
        if dynamic_skill_text:
            formatted_blocks.append(dynamic_skill_text.rstrip())

    if len(formatted_blocks) == 0:
        return None

    at_files_str = "\n\n".join(formatted_blocks)
    ui_items: list[model.DeveloperUIItem] = [model.AtFileOpsUIItem(ops=at_ops)]
    if collected_image_paths:
        ui_items.append(model.AtFileImagesUIItem(paths=collected_image_paths))
    if discovered_memories:
        loaded_files = [model.MemoryFileLoaded(path=m.path) for m in discovered_memories]
        ui_items.append(model.MemoryLoadedUIItem(files=loaded_files))
    if dynamic_skill_attachment is not None and dynamic_skill_attachment.ui_extra is not None:
        ui_items.extend(dynamic_skill_attachment.ui_extra.items)
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
        if status.is_directory:
            continue
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
            fmt_file_changed_externally(file_path, file_content)
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
        if isinstance(item, message.ToolResultMessage) and item.tool_name == tools.READ and path in item.output_text:
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


def _get_dynamic_skills_for_session(session: Session) -> list[Skill]:
    if not session.file_tracker:
        return []
    return discover_skills_near_paths(session.file_tracker.keys(), work_dir=session.work_dir)


def _find_dynamic_skill(session: Session, name: str, *, allow_short_fallback: bool = False) -> Skill | None:
    dynamic_skills = _get_dynamic_skills_for_session(session)
    by_name = {skill.name: skill for skill in dynamic_skills}

    skill = by_name.get(name)
    if skill is not None:
        return skill

    if allow_short_fallback and ":" in name:
        return by_name.get(name.split(":")[-1])

    return None


def _resolve_skill_for_input(session: Session, skill_name: str) -> Skill | None:
    dynamic_exact = _find_dynamic_skill(session, skill_name)
    if dynamic_exact is not None:
        return dynamic_exact

    static_exact = get_skill_loader().loaded_skills.get(skill_name)
    if static_exact is not None:
        return static_exact

    if ":" in skill_name:
        dynamic_short = _find_dynamic_skill(session, skill_name, allow_short_fallback=True)
        if dynamic_short is not None:
            return dynamic_short
        return get_skill(skill_name.split(":")[-1])

    return get_skill(skill_name)


def _read_skill_content(skill: Skill) -> str | None:
    if not skill.skill_path.exists() or not skill.skill_path.is_file():
        return None
    content = skill.skill_path.read_text(encoding="utf-8", errors="replace")
    return content or None


def _mark_skill_loaded(session: Session, path: str, content: str, *, source: Literal["dynamic", "explicit"]) -> None:
    existing = session.file_tracker.get(path)
    try:
        mtime = Path(path).stat().st_mtime
    except (OSError, FileNotFoundError):
        mtime = 0.0
    session.file_tracker[path] = model.FileStatus(
        mtime=mtime,
        content_sha256=hash_text_sha256(content),
        is_memory=existing.is_memory if existing else False,
        is_skill=True,
        skill_attachment_source=source,
        is_directory=existing.is_directory if existing else False,
        read_complete=existing.read_complete if existing else False,
    )


def _mark_directory_accessed(session: Session, path: str) -> None:
    existing = session.file_tracker.get(path)
    try:
        mtime = Path(path).stat().st_mtime
    except (OSError, FileNotFoundError):
        mtime = 0.0
    session.file_tracker[path] = model.FileStatus(
        mtime=mtime,
        content_sha256=None,
        is_memory=existing.is_memory if existing else False,
        is_skill=existing.is_skill if existing else False,
        skill_attachment_source=existing.skill_attachment_source if existing else None,
        is_directory=True,
        read_complete=existing.read_complete if existing else False,
    )


def _get_loaded_skill_paths_by_name(session: Session, *, dynamic_only: bool) -> dict[str, str]:
    loader = SkillLoader()
    result: dict[str, str] = {}

    for path, status in session.file_tracker.items():
        if not status.is_skill:
            continue
        if dynamic_only and status.skill_attachment_source != "dynamic":
            continue
        skill = loader.load_skill(Path(path), location="project")
        if skill is None:
            continue
        result[skill.name] = path

    return result


def _format_skill_block_str(skill: Skill, skill_content: str, *, explicit: bool, supersedes_previous: bool) -> str:
    return fmt_skill_block(
        skill_name=skill.name,
        skill_path=skill.skill_path,
        base_dir=skill.base_dir,
        skill_content=skill_content,
        explicit=explicit,
        supersedes_previous=supersedes_previous,
    )


def _format_dynamic_available_skills_str(skills: list[Skill], *, supersedes_previous: bool) -> str:
    loader = SkillLoader()
    loader.loaded_skills = {skill.name: skill for skill in skills}
    skills_xml = loader.get_skills_xml().rstrip()
    return fmt_dynamic_available_skills(skills_xml, supersedes_previous=supersedes_previous)


def _collect_skill_blocks(session: Session, skills: list[Skill], *, explicit: bool) -> tuple[list[str], list[Skill]]:
    skill_blocks: list[str] = []
    activated_skills: list[Skill] = []
    loaded_dynamic_paths_by_name = _get_loaded_skill_paths_by_name(session, dynamic_only=True)
    loaded_all_paths_by_name = _get_loaded_skill_paths_by_name(session, dynamic_only=False)

    for skill in skills:
        skill_content = _read_skill_content(skill)
        if skill_content is None:
            continue

        skill_path = str(skill.skill_path)
        if explicit:
            existing_path = None
        else:
            non_dynamic_path = loaded_all_paths_by_name.get(skill.name)
            dynamic_path = loaded_dynamic_paths_by_name.get(skill.name)
            if non_dynamic_path is not None and non_dynamic_path != dynamic_path:
                continue
            existing_path = dynamic_path

        if not explicit and existing_path == skill_path and _is_tracked_file_unchanged(session, skill_path):
            continue

        supersedes_previous = existing_path is not None and existing_path != skill_path
        if supersedes_previous:
            assert existing_path is not None
            session.file_tracker.pop(existing_path, None)

        _mark_skill_loaded(session, skill_path, skill_content, source="explicit" if explicit else "dynamic")
        loaded_dynamic_paths_by_name[skill.name] = skill_path
        loaded_all_paths_by_name[skill.name] = skill_path
        skill_blocks.append(
            _format_skill_block_str(
                skill,
                skill_content,
                explicit=explicit,
                supersedes_previous=supersedes_previous,
            )
        )
        activated_skills.append(skill)

    return skill_blocks, activated_skills


def _collect_dynamic_skills(session: Session, skills: list[Skill]) -> tuple[list[Skill], bool]:
    activated_skills: list[Skill] = []
    loaded_dynamic_paths_by_name = _get_loaded_skill_paths_by_name(session, dynamic_only=True)
    loaded_all_paths_by_name = _get_loaded_skill_paths_by_name(session, dynamic_only=False)
    superseded_any = False

    for skill in skills:
        skill_content = _read_skill_content(skill)
        if skill_content is None:
            continue

        skill_path = str(skill.skill_path)
        non_dynamic_path = loaded_all_paths_by_name.get(skill.name)
        dynamic_path = loaded_dynamic_paths_by_name.get(skill.name)
        if non_dynamic_path is not None and non_dynamic_path != dynamic_path:
            continue

        existing_path = dynamic_path
        if existing_path == skill_path and _is_tracked_file_unchanged(session, skill_path):
            continue

        supersedes_previous = existing_path is not None and existing_path != skill_path
        if supersedes_previous:
            assert existing_path is not None
            session.file_tracker.pop(existing_path, None)
            superseded_any = True

        _mark_skill_loaded(session, skill_path, skill_content, source="dynamic")
        loaded_dynamic_paths_by_name[skill.name] = skill_path
        loaded_all_paths_by_name[skill.name] = skill_path
        activated_skills.append(skill)

    return activated_skills, superseded_any


def _build_skill_attachment(session: Session, skills: list[Skill], *, explicit: bool) -> message.DeveloperMessage | None:
    skill_blocks, activated_skills = _collect_skill_blocks(session, skills, explicit=explicit)

    if not skill_blocks:
        return None

    ui_items: list[model.DeveloperUIItem] = [model.SkillActivatedUIItem(name=skill.name) for skill in activated_skills]

    return message.DeveloperMessage(
        parts=message.text_parts_from_str(f"<system-reminder>{chr(10).join(skill_blocks)}\n</system-reminder>"),
        ui_extra=model.DeveloperUIExtra(items=ui_items),
    )


def _build_dynamic_skill_listing_attachment(session: Session, skills: list[Skill]) -> message.DeveloperMessage | None:
    activated_skills, superseded_any = _collect_dynamic_skills(session, skills)
    if not activated_skills:
        return None

    content = _format_dynamic_available_skills_str(activated_skills, supersedes_previous=superseded_any)
    ui_items: list[model.DeveloperUIItem] = [model.SkillDiscoveredUIItem(name=skill.name) for skill in activated_skills]
    return message.DeveloperMessage(
        parts=message.text_parts_from_str(f"<system-reminder>{content}\n</system-reminder>"),
        ui_extra=model.DeveloperUIExtra(items=ui_items),
    )


async def skill_attachment(session: Session) -> message.DeveloperMessage | None:
    """Load skill content when user references skills with explicit skill syntax."""
    skill_names = get_skills_from_user_input(session)
    if not skill_names:
        return None

    resolved_skills: list[Skill] = []
    seen_paths: set[str] = set()

    for skill_name in skill_names:
        skill = _resolve_skill_for_input(session, skill_name)
        if not skill:
            continue
        skill_path = str(skill.skill_path)
        if skill_path in seen_paths:
            continue
        seen_paths.add(skill_path)
        resolved_skills.append(skill)

    return _build_skill_attachment(session, resolved_skills, explicit=True)


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
    existing = session.file_tracker.get(path)
    session.file_tracker[path] = model.FileStatus(
        mtime=mtime,
        content_sha256=content_sha256,
        is_memory=True,
        is_skill=existing.is_skill if existing else False,
        skill_attachment_source=existing.skill_attachment_source if existing else None,
        is_directory=existing.is_directory if existing else False,
        read_complete=existing.read_complete if existing else False,
    )


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
                text = truncate_memory_content(text, path_str)
                text_bytes = len(text.encode("utf-8"))
                if text_bytes > remaining_budget:
                    # Would exceed session budget; truncate further or skip
                    if remaining_budget > 256:
                        text = text.encode("utf-8")[:remaining_budget].decode("utf-8", errors="ignore")
                        text += fmt_memory_truncated(MEMORY_MAX_SESSION_BYTES)
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
            auto_mem_content = truncate_memory_content(auto_mem.content, auto_mem.path)
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
            auto_memory_hint = fmt_auto_memory_hint(auto_memory_path)

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


async def last_path_skill_attachment(session: Session) -> message.DeveloperMessage | None:
    """Announce nested project-local skills discovered near accessed paths."""
    dynamic_skills = _get_dynamic_skills_for_session(session)
    if not dynamic_skills:
        return None
    return _build_dynamic_skill_listing_attachment(session, dynamic_skills)


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
        todo_items_str = "\n".join(f"{i + 1}. [{t.status}] {t.content}" for i, t in enumerate(session.todos))
        todo_str = fmt_todo_items(todo_items_str)

    content = fmt_todo_nudge(todo_str)

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
# - last_path_skill_attachment reads and updates file_tracker using accessed paths
# These form a sequential phase. Others (memory_attachment, image_attachment,
# skill_attachment, todo_attachment) are independent and safe to parallelize.
_SEQUENTIAL_ATTACHMENTS: frozenset[str] = frozenset(
    {
        "at_file_reader_attachment",
        "file_changed_externally_attachment",
        "last_path_memory_attachment",
        "last_path_skill_attachment",
    }
)


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
