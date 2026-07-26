import json

from rich.console import Group, RenderableType
from rich.text import Text

from klaude_code.const import INVALID_TOOL_CALL_MAX_LENGTH
from klaude_code.protocol import tools
from klaude_code.tui.components.rich.theme import ThemeKey
from klaude_code.tui.components.tools._common import MARK_EDIT, MARK_WRITE, render_path, render_tool_call_tree
from klaude_code.tui.components.tools._presentation import apply_patch_file_paths, get_tool_display_name


def render_edit_tool_call(arguments: str) -> RenderableType:
    tool_name = get_tool_display_name(tools.EDIT, arguments)
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
    tool_name = get_tool_display_name(tools.WRITE, arguments)
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
    tool_name = get_tool_display_name(tools.APPLY_PATCH, arguments)

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
        file_paths = apply_patch_file_paths(arguments)
        if len(file_paths) == 1:
            details = render_path(file_paths[0], ThemeKey.TOOL_PARAM_FILE_PATH)
        elif file_paths:
            details = Text(f"{len(file_paths)} files", ThemeKey.TOOL_PARAM)
        else:
            details = Text("", ThemeKey.TOOL_PARAM)
    else:
        details = Text(
            str(patch_content)[:INVALID_TOOL_CALL_MAX_LENGTH],
            ThemeKey.INVALID_TOOL_CALL_ARGS,
        )

    return render_tool_call_tree(mark=MARK_EDIT, tool_name=tool_name, details=details)
