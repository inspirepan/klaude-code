import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

from klaude_code.protocol import tools
from klaude_code.tui.components.bash_syntax import summarize_bash_command
from klaude_code.tui.components.common import format_pascal_case, shorten_path

SubjectKind = Literal["default", "path", "bash"]


@dataclass(frozen=True)
class ToolCallPresentation:
    """Layout-independent identity and one-line subject for a tool call."""

    name: str
    subject: str = ""
    subject_kind: SubjectKind = "default"


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    active_form: str


_TOOL_DEFINITIONS: dict[str, ToolDefinition] = {
    tools.BASH: ToolDefinition("Bash", "Bashing"),
    tools.APPLY_PATCH: ToolDefinition("Patch", "Patching"),
    tools.EDIT: ToolDefinition("Edit", "Editing"),
    tools.READ: ToolDefinition("Read", "Reading"),
    tools.LOOK_AT: ToolDefinition("Look At", "Looking At Image"),
    tools.WRITE: ToolDefinition("Write", "Writing"),
    tools.TODO_WRITE: ToolDefinition("Update To-Dos", "Updating Todos"),
    tools.WEB_FETCH: ToolDefinition("Fetch Web", "Fetching Web"),
    tools.WEB_SEARCH: ToolDefinition("Search Web", "Searching Web"),
    tools.AGENT: ToolDefinition("Agent", "Running Task"),
    tools.REWIND: ToolDefinition("Rewind", "Rewinding"),
    tools.ASK_USER_QUESTION: ToolDefinition("Agent has a question for you", "Questioning"),
    tools.HANDOFF: ToolDefinition("Handoff", "Packing Context"),
}


def parse_tool_arguments(arguments: str) -> dict[str, object]:
    try:
        value: Any = json.loads(arguments)
    except json.JSONDecodeError:
        return {}
    return cast(dict[str, object], value) if isinstance(value, dict) else {}


def one_line(value: object) -> str:
    return " ".join(str(value).replace("\\\n", " ").split())


def display_path(value: object) -> str:
    if not isinstance(value, str) or not value:
        return one_line(value)
    path = shorten_path(value)
    return path if path.startswith(("/", ".", "~")) else f"./{path}"


def _apply_patch_file_paths(args: dict[str, object]) -> list[str]:
    patch = args.get("patch")
    if not isinstance(patch, str):
        return []
    prefixes = ("*** Update File:", "*** Add File:", "*** Delete File:")
    return [
        line.removeprefix(prefix).strip()
        for line in patch.splitlines()
        for prefix in prefixes
        if line.startswith(prefix)
    ]


def _tool_display_name(tool_name: str, args: dict[str, object]) -> str:
    if tool_name == tools.READ:
        file_path = args.get("file_path")
        if isinstance(file_path, str) and Path(file_path).name == "SKILL.md":
            return "Read Skill"
    if tool_name == tools.ASK_USER_QUESTION:
        questions = args.get("questions")
        if isinstance(questions, list) and len(questions) > 1:
            return f"Agent has {len(questions)} questions for you"
    definition = _TOOL_DEFINITIONS.get(tool_name)
    return definition.name if definition is not None else format_pascal_case(tool_name)


def get_tool_display_name(tool_name: str, arguments: str = "") -> str:
    """Return the canonical TUI label for a protocol tool name."""
    return _tool_display_name(tool_name, parse_tool_arguments(arguments))


def apply_patch_file_paths(arguments: str) -> list[str]:
    return _apply_patch_file_paths(parse_tool_arguments(arguments))


def get_tool_active_form(tool_name: str) -> str:
    """Return the canonical running-state label for a protocol tool name."""
    definition = _TOOL_DEFINITIONS.get(tool_name)
    return definition.active_form if definition is not None else f"Calling {tool_name}"


def get_tool_call_presentation(tool_name: str, arguments: str) -> ToolCallPresentation:
    """Return shared tool identity and compact subject semantics."""
    args = parse_tool_arguments(arguments)
    name = _tool_display_name(tool_name, args)

    if tool_name == tools.READ:
        subject = display_path(args.get("file_path", ""))
        offset = args.get("offset")
        limit = args.get("limit")
        offset_int = offset if isinstance(offset, int) and not isinstance(offset, bool) else None
        limit_int = limit if isinstance(limit, int) and not isinstance(limit, bool) else None
        if offset_int is not None and limit_int is not None:
            subject += f" {offset_int}:{offset_int + limit_int - 1}"
        elif limit_int is not None and offset is None:
            subject += f" 1:{limit_int}"
        elif offset_int is not None and limit is None:
            subject += f" {offset_int}:-"
        return ToolCallPresentation(name, subject, "path")

    if tool_name in (tools.EDIT, tools.WRITE):
        return ToolCallPresentation(name, display_path(args.get("file_path", "")), "path")

    if tool_name == tools.APPLY_PATCH:
        paths = _apply_patch_file_paths(args)
        if len(paths) == 1:
            return ToolCallPresentation(name, display_path(paths[0]), "path")
        return ToolCallPresentation(name, f"{len(paths)} files" if paths else "")

    if tool_name == tools.BASH:
        description = one_line(args.get("description", ""))
        command = summarize_bash_command(str(args.get("command", "")))
        return ToolCallPresentation(name, "  ".join(part for part in (description, command) if part), "bash")

    if tool_name == tools.WEB_SEARCH:
        return ToolCallPresentation(name, one_line(args.get("query", "")))

    if tool_name == tools.WEB_FETCH:
        return ToolCallPresentation(name, one_line(args.get("url", "")), "path")

    if tool_name == tools.REWIND:
        checkpoint_id = args.get("checkpoint_id")
        rationale = one_line(args.get("rationale", ""))
        checkpoint = f"Checkpoint {checkpoint_id}" if isinstance(checkpoint_id, int) else ""
        return ToolCallPresentation(name, " - ".join(part for part in (checkpoint, rationale) if part))

    if tool_name == tools.ASK_USER_QUESTION:
        questions = args.get("questions")
        headers: list[str] = []
        if isinstance(questions, list):
            for question in questions:
                if not isinstance(question, dict):
                    continue
                question_dict = cast(dict[str, object], question)
                header = question_dict.get("header")
                if header:
                    headers.append(str(header))
        return ToolCallPresentation(name, " / ".join(headers))

    for key in ("description", "query", "file_path", "path", "url", "command"):
        if args.get(key):
            kind: SubjectKind = "path" if key in ("file_path", "path") else "default"
            subject = display_path(args[key]) if kind == "path" else one_line(args[key])
            return ToolCallPresentation(name, subject, kind)
    return ToolCallPresentation(name)
