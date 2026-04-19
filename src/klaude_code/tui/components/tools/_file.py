import json

from rich.console import Group, RenderableType
from rich.text import Text

from klaude_code.const import INVALID_TOOL_CALL_MAX_LENGTH
from klaude_code.tui.components.rich.theme import ThemeKey
from klaude_code.tui.components.tools._common import MARK_EDIT, MARK_WRITE, render_path, render_tool_call_tree


def render_edit_tool_call(arguments: str) -> RenderableType:
    tool_name = "Edit"
    try:
        json_dict = json.loads(arguments)
        file_path = json_dict.get("file_path")
        replace_all = json_dict.get("replace_all", False)
        path_text = render_path(file_path, ThemeKey.TOOL_PARAM_FILE_PATH)
        if replace_all:
            old_string = json_dict.get("old_string", "")
            new_string = json_dict.get("new_string", "")
            replace_info = Text("Replacing all ", ThemeKey.TOOL_RESULT_TRUNCATED)
            replace_info.append(old_string, ThemeKey.BASH_STRING)
            replace_info.append(" \u2192 ", ThemeKey.BASH_OPERATOR)
            replace_info.append(new_string, ThemeKey.BASH_STRING)
            details: RenderableType = Group(path_text, replace_info)
        else:
            details = path_text
    except json.JSONDecodeError:
        details = Text(
            arguments.strip()[:INVALID_TOOL_CALL_MAX_LENGTH],
            style=ThemeKey.INVALID_TOOL_CALL_ARGS,
        )
    return render_tool_call_tree(mark=MARK_EDIT, tool_name=tool_name, details=details)


def render_write_tool_call(arguments: str) -> RenderableType:
    tool_name = "Write"
    try:
        json_dict = json.loads(arguments)
        file_path = json_dict.get("file_path", "")
        details: RenderableType | None = render_path(file_path, ThemeKey.TOOL_PARAM_FILE_PATH)
    except json.JSONDecodeError:
        details = Text(
            arguments.strip()[:INVALID_TOOL_CALL_MAX_LENGTH],
            style=ThemeKey.INVALID_TOOL_CALL_ARGS,
        )
    return render_tool_call_tree(mark=MARK_WRITE, tool_name=tool_name, details=details)


def render_apply_patch_tool_call(arguments: str) -> RenderableType:
    tool_name = "Patch"

    try:
        payload = json.loads(arguments)
    except json.JSONDecodeError:
        details = Text(
            arguments.strip()[:INVALID_TOOL_CALL_MAX_LENGTH],
            style=ThemeKey.INVALID_TOOL_CALL_ARGS,
        )
        return render_tool_call_tree(mark=MARK_EDIT, tool_name=tool_name, details=details)

    patch_content = payload.get("patch", "")
    details: RenderableType = Text("", ThemeKey.TOOL_PARAM)

    if isinstance(patch_content, str):
        update_files: list[str] = []
        add_files: list[str] = []
        delete_files: list[str] = []
        for line in patch_content.splitlines():
            if line.startswith("*** Update File:"):
                update_files.append(line[len("*** Update File:") :].strip())
            elif line.startswith("*** Add File:"):
                add_files.append(line[len("*** Add File:") :].strip())
            elif line.startswith("*** Delete File:"):
                delete_files.append(line[len("*** Delete File:") :].strip())

        summary = Text("", ThemeKey.TOOL_PARAM)
        if update_files:
            summary.append(f"Edit \u00d7 {len(update_files)}")
        if add_files:
            if summary.plain:
                summary.append(", ")
            # For single .md file addition, show filename in parentheses
            if len(add_files) == 1 and add_files[0].endswith(".md"):
                summary.append("Create ")
                summary.append_text(render_path(add_files[0], ThemeKey.TOOL_PARAM_FILE_PATH))
            else:
                summary.append(f"Create \u00d7 {len(add_files)}")
        if delete_files:
            if summary.plain:
                summary.append(", ")
            summary.append(f"Delete \u00d7 {len(delete_files)}")
        details = summary
    else:
        details = Text(
            str(patch_content)[:INVALID_TOOL_CALL_MAX_LENGTH],
            ThemeKey.INVALID_TOOL_CALL_ARGS,
        )

    return render_tool_call_tree(mark=MARK_EDIT, tool_name=tool_name, details=details)
