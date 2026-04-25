from __future__ import annotations

import difflib
import re
import shlex
from pathlib import Path

from klaude_code.const import ATTACHMENT_DIFF_MAX_LINES, ATTACHMENT_DIFF_SOURCE_MAX_BYTES
from klaude_code.prompts.attachments import (
    FILE_ALREADY_IN_CONTEXT_TEMPLATE,
    FILE_CHANGED_DIFF_SKIPPED_TEMPLATE,
    FILE_CHANGED_DIFF_TRUNCATED_TEMPLATE,
    FILE_CHANGED_EXTERNALLY_TEMPLATE,
    PASTE_FILE_HINT_TEMPLATE,
    TOOL_RESULT_TEMPLATE,
)
from klaude_code.protocol import message, tools
from klaude_code.protocol.models import (
    AtFileImagesUIItem,
    AtFileOp,
    AtFileOpsUIItem,
    DeveloperUIExtra,
    DeveloperUIItem,
    ExternalFileChangesUIItem,
    MemoryFileLoaded,
    MemoryLoadedUIItem,
    PasteFilesUIItem,
    UserImagesUIItem,
)
from klaude_code.session import Session
from klaude_code.skill.loader import discover_skills_near_paths
from klaude_code.tool import BashTool, ReadTool

from . import truncate_text_by_lines
from .memory import Memory, discover_memory_files_near_paths, format_memory_content
from .skills import build_dynamic_skill_listing_attachment
from .state import (
    build_attachment_tool_context,
    compute_file_content_sha256,
    is_memory_loaded,
    is_tracked_file_unchanged,
    mark_directory_accessed,
    mark_memory_loaded,
)


def _fmt_file_already_in_context(path: str, read_tool_name: str) -> str:
    return FILE_ALREADY_IN_CONTEXT_TEMPLATE.format(path=path, read_tool_name=read_tool_name)


def _fmt_tool_result(tool_name: str, tool_args: str, output: str) -> str:
    return TOOL_RESULT_TEMPLATE.format(tool_name=tool_name, tool_args=tool_args, output=output)


def _fmt_file_changed_externally(file_path: str, file_content: str) -> str:
    return FILE_CHANGED_EXTERNALLY_TEMPLATE.format(file_path=file_path, file_content=file_content)


def _fmt_paste_file_hint(pasted_files: dict[str, str]) -> str:
    mapping = "\n".join(f"- <{tag}> saved to: {path}" for tag, path in pasted_files.items())
    return PASTE_FILE_HINT_TEMPLATE.format(mapping=mapping)


# Match @ preceded by whitespace, start of line, or -> (ReadTool line number arrow)
# Supports optional line range suffix: @file.txt#L10-20 or @file.txt#L10.
_AT_PLAIN_STOP_CHARS = (
    r"\u3000-\u303f"
    r"\uff01-\uff0f"
    r"\uff1a-\uff20"
    r"\uff3b-\uff40"
    r"\uff5b-\uff65"
)
AT_FILE_PATTERN = re.compile(rf'(?:(?<!\S)|(?<=\u2192))@("(?P<quoted>[^"]+)"|(?P<plain>[^\s{_AT_PLAIN_STOP_CHARS}]+))')


class AtFileRef:
    """Parsed @file reference with optional line range."""

    __slots__ = ("line_end", "line_start", "path")

    def __init__(self, path: str, line_start: int | None = None, line_end: int | None = None) -> None:
        self.path = path
        self.line_start = line_start
        self.line_end = line_end


def _parse_at_file_ref(raw: str) -> AtFileRef:
    match = re.match(r"^(.+?)#L(\d+)(?:-(\d+))?$", raw)
    if not match:
        return AtFileRef(raw)

    base_path = match.group(1)
    if Path(raw).resolve().exists():
        return AtFileRef(raw)
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


async def _load_at_file(
    session: Session,
    ref: AtFileRef,
    at_ops: list[AtFileOp],
    formatted_blocks: list[str],
    collected_images: list[message.ImageURLPart],
    collected_image_paths: list[str],
    discovered_memories: list[Memory],
    skill_discovery_paths: list[str],
) -> None:
    path = Path(ref.path).resolve()
    path_str = str(path)
    tool_context = build_attachment_tool_context(session)

    if path.exists() and path.is_file():
        if is_tracked_file_unchanged(session, path_str) and ref.line_start is None:
            at_ops.append(AtFileOp(operation="Read", path=path_str))
            formatted_blocks.append(_fmt_file_already_in_context(path_str, tools.READ))
            return

        offset: int | None = ref.line_start
        limit: int | None = None
        if ref.line_end is not None and ref.line_start is not None:
            limit = ref.line_end - ref.line_start + 1
        args = ReadTool.ReadArguments(file_path=path_str, offset=offset, limit=limit)
        tool_result = await ReadTool.call_with_args(args, tool_context)
        images = [part for part in tool_result.parts if isinstance(part, message.ImageURLPart)]

        formatted_blocks.append(
            _fmt_tool_result(tools.READ, args.model_dump_json(exclude_none=True), tool_result.output_text)
        )
        at_ops.append(AtFileOp(operation="Read", path=path_str))
        if images:
            collected_images.extend(images)
            collected_image_paths.append(path_str)
        return

    if path.exists() and path.is_dir():
        quoted_path = shlex.quote(path_str)
        args = BashTool.BashArguments(command=f"ls {quoted_path}")
        tool_result = await BashTool.call_with_args(args, tool_context)

        formatted_blocks.append(
            _fmt_tool_result(tools.BASH, args.model_dump_json(exclude_none=True), tool_result.output_text)
        )
        at_ops.append(AtFileOp(operation="List", path=path_str + "/"))
        mark_directory_accessed(session, path_str)

        new_memories = discover_memory_files_near_paths(
            [path_str],
            work_dir=session.work_dir,
            is_memory_loaded=lambda p: is_memory_loaded(session, p),
            mark_memory_loaded=lambda p: mark_memory_loaded(session, p),
        )
        for memory in new_memories:
            formatted_blocks.append(format_memory_content(memory))
            discovered_memories.append(memory)
        skill_discovery_paths.append(path_str)


def _unwrap_system_reminder(text: str) -> str:
    if text.startswith("<system-reminder>") and text.endswith("</system-reminder>"):
        return text.removeprefix("<system-reminder>").removesuffix("</system-reminder>")
    return text


def _append_dynamic_skill_listing(
    session: Session,
    skill_discovery_paths: list[str],
    formatted_blocks: list[str],
    ui_items: list[DeveloperUIItem],
) -> None:
    dynamic_skill_attachment = build_dynamic_skill_listing_attachment(
        session,
        discover_skills_near_paths(skill_discovery_paths, work_dir=session.work_dir),
    )
    if dynamic_skill_attachment is None:
        return

    dynamic_skill_text = _unwrap_system_reminder(message.join_text_parts(dynamic_skill_attachment.parts)).rstrip()
    if dynamic_skill_text:
        formatted_blocks.append(dynamic_skill_text)
    if dynamic_skill_attachment.ui_extra is not None:
        ui_items.extend(dynamic_skill_attachment.ui_extra.items)


async def at_file_reader_attachment(session: Session) -> message.DeveloperMessage | None:
    """Parse @foo/bar references from the last user message and load them."""

    refs = get_at_patterns(session)
    if not refs:
        return None

    at_ops: list[AtFileOp] = []
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

    ui_items: list[DeveloperUIItem] = [AtFileOpsUIItem(ops=at_ops)]
    _append_dynamic_skill_listing(
        session,
        skill_discovery_paths,
        formatted_blocks,
        ui_items,
    )

    if not formatted_blocks:
        return None

    if collected_image_paths:
        ui_items.append(AtFileImagesUIItem(paths=collected_image_paths))
    if discovered_memories:
        ui_items.append(
            MemoryLoadedUIItem(files=[MemoryFileLoaded(path=memory.path) for memory in discovered_memories])
        )

    return message.DeveloperMessage(
        parts=message.parts_from_text_and_images(
            f"<system-reminder>{'\n\n'.join(formatted_blocks)}\n</system-reminder>",
            collected_images or None,
        ),
        ui_extra=DeveloperUIExtra(items=ui_items),
    )


def _compute_diff_snippet(old_content: str, new_content: str, file_path: str) -> str:
    """Render a small unified-style diff, capped so it cannot blow up context.

    Guards (see ``const.ATTACHMENT_DIFF_*``):

    * If ``old_content + new_content`` already exceeds the source size limit,
      skip ``difflib`` entirely. Large HTML/minified blobs produce diffs that
      approach ``2x`` the source, which in past sessions pushed the next turn
      past the 1M-token ceiling even after a successful compaction.
    * After the diff is built, keep only the first ``ATTACHMENT_DIFF_MAX_LINES``
      lines and append a Read-tool-style notice, mirroring how the Read tool
      truncates long files.
    """
    combined_size_bytes = len(old_content.encode("utf-8")) + len(new_content.encode("utf-8"))
    if combined_size_bytes > ATTACHMENT_DIFF_SOURCE_MAX_BYTES:
        return FILE_CHANGED_DIFF_SKIPPED_TEMPLATE.format(
            total_bytes=combined_size_bytes,
            limit_bytes=ATTACHMENT_DIFF_SOURCE_MAX_BYTES,
            file_path=file_path,
        )

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

    rendered = "\n".join(diff_lines).rstrip("\n -")
    truncation = truncate_text_by_lines(rendered, max_lines=ATTACHMENT_DIFF_MAX_LINES)
    if truncation.truncated:
        return truncation.text + FILE_CHANGED_DIFF_TRUNCATED_TEMPLATE.format(
            hidden_lines=truncation.hidden_lines,
            total_lines=truncation.total_lines,
            file_path=file_path,
        )
    return truncation.text


async def file_changed_externally_attachment(session: Session) -> message.DeveloperMessage | None:
    """Notify agent about user/linter changes, showing a diff snippet when possible."""

    if not session.file_tracker:
        return None

    changed_files: list[tuple[str, str]] = []
    collected_images: list[message.ImageURLPart] = []
    for path, status in list(session.file_tracker.items()):
        if status.is_directory:
            continue
        try:
            current_mtime = Path(path).stat().st_mtime
            if status.content_sha256 is not None:
                current_sha256 = compute_file_content_sha256(path)
                changed = current_sha256 is not None and current_sha256 != status.content_sha256
            else:
                changed = current_mtime != status.mtime
            if not changed:
                continue

            old_content = status.cached_content
            tool_result = await ReadTool.call_with_args(
                ReadTool.ReadArguments(file_path=path), build_attachment_tool_context(session)
            )
            if tool_result.status != "success" or old_content is None:
                continue

            images = [part for part in tool_result.parts if isinstance(part, message.ImageURLPart)]
            new_status = session.file_tracker.get(path)
            if new_status is None or new_status.cached_content is None:
                continue

            snippet = _compute_diff_snippet(old_content, new_status.cached_content, path)
            if not snippet:
                continue
            changed_files.append((path, snippet))
            if images:
                collected_images.extend(images)
        except (FileNotFoundError, IsADirectoryError, OSError, PermissionError, UnicodeDecodeError):
            continue

    if not changed_files:
        return None

    changed_files_str = "\n\n".join(
        _fmt_file_changed_externally(file_path, file_content) for file_path, file_content in changed_files
    )
    return message.DeveloperMessage(
        parts=message.parts_from_text_and_images(
            f"<system-reminder>{changed_files_str}</system-reminder>",
            collected_images or None,
        ),
        ui_extra=DeveloperUIExtra(
            items=[ExternalFileChangesUIItem(paths=[file_path for file_path, _ in changed_files])]
        ),
    )


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
                elif isinstance(part, message.ImageURLPart) and part.source_file_path:
                    paths.append(part.source_file_path)
            return paths
    return []


async def image_attachment(session: Session) -> message.DeveloperMessage | None:
    """Attach images from the last user message."""

    image_paths = get_last_user_message_image_paths(session)
    if not image_paths:
        return None
    return message.DeveloperMessage(
        parts=[],
        ui_extra=DeveloperUIExtra(items=[UserImagesUIItem(count=len(image_paths), paths=image_paths)]),
    )


async def paste_file_attachment(session: Session) -> message.DeveloperMessage | None:
    """Remind agent about paste files the user provided."""

    for item in reversed(session.conversation_history):
        if isinstance(item, message.ToolResultMessage):
            return None
        if (
            isinstance(item, message.DeveloperMessage)
            and item.ui_extra is not None
            and any(isinstance(ui_item, PasteFilesUIItem) for ui_item in item.ui_extra.items)
        ):
            return None
        if isinstance(item, message.UserMessage):
            if not item.pasted_files:
                return None
            return message.DeveloperMessage(
                parts=message.text_parts_from_str(
                    f"<system-reminder>{_fmt_paste_file_hint(item.pasted_files)}\n</system-reminder>"
                ),
                ui_extra=DeveloperUIExtra(items=[PasteFilesUIItem(tags=item.pasted_files)]),
            )
    return None
