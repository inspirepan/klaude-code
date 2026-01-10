from rich.console import RenderableType
from rich.text import Text

from klaude_code.const import DIFF_PREFIX_WIDTH, TAB_EXPAND_WIDTH
from klaude_code.protocol import model
from klaude_code.tui.components.common import create_grid
from klaude_code.tui.components.rich.theme import ThemeKey


def render_structured_diff(ui_extra: model.DiffUIExtra, show_file_name: bool = False) -> RenderableType:
    files = ui_extra.files
    if not files:
        return Text("")

    grid = create_grid()
    grid.padding = (0, 0)
    show_headers = show_file_name or len(files) > 1

    for idx, file_diff in enumerate(files):
        if idx > 0:
            grid.add_row("", "")

        if show_headers:
            grid.add_row(*_render_file_header(file_diff))

        for line in file_diff.lines:
            prefix = _make_structured_prefix(line, DIFF_PREFIX_WIDTH)
            text = _render_structured_line(line)
            grid.add_row(Text(prefix, ThemeKey.TOOL_RESULT), text)

    return grid


def _render_file_header(file_diff: model.DiffFileDiff) -> tuple[Text, Text]:
    file_text = Text(file_diff.file_path, style=ThemeKey.DIFF_FILE_NAME)
    stats_text = Text()
    if file_diff.stats_add > 0:
        stats_text.append(f"+{file_diff.stats_add}", style=ThemeKey.DIFF_STATS_ADD)
    if file_diff.stats_remove > 0:
        if stats_text.plain:
            stats_text.append(" ")
        stats_text.append(f"-{file_diff.stats_remove}", style=ThemeKey.DIFF_STATS_REMOVE)

    file_line = Text(style=ThemeKey.DIFF_FILE_NAME)
    file_line.append_text(file_text)
    if stats_text.plain:
        file_line.append(" (")
        file_line.append_text(stats_text)
        file_line.append(")")

    if file_diff.stats_add > 0 and file_diff.stats_remove == 0:
        file_mark = "+"
    elif file_diff.stats_remove > 0 and file_diff.stats_add == 0:
        file_mark = "-"
    else:
        file_mark = "±"

    prefix = Text(f"{file_mark:>{DIFF_PREFIX_WIDTH}}  ", style=ThemeKey.DIFF_FILE_NAME)
    return prefix, file_line


def _make_structured_prefix(line: model.DiffLine, width: int) -> str:
    if line.kind == "gap":
        return f"{'⋮':>{width}}  "
    number = " " * width
    if line.kind in {"add", "ctx"} and line.new_line_no is not None:
        number = f"{line.new_line_no:>{width}}"
    marker = "+" if line.kind == "add" else "-" if line.kind == "remove" else " "
    return f"{number} {marker}"


def _render_structured_line(line: model.DiffLine) -> Text:
    if line.kind == "gap":
        return Text("")
    text = Text()
    for span in line.spans:
        content = span.text.expandtabs(TAB_EXPAND_WIDTH)
        text.append(content, style=_span_style(line.kind, span.op))
    return text


def _span_style(line_kind: str, span_op: str) -> ThemeKey:
    if line_kind == "add":
        if span_op == "insert":
            return ThemeKey.DIFF_ADD_CHAR
        return ThemeKey.DIFF_ADD
    if line_kind == "remove":
        if span_op == "delete":
            return ThemeKey.DIFF_REMOVE_CHAR
        return ThemeKey.DIFF_REMOVE
    return ThemeKey.TOOL_RESULT
