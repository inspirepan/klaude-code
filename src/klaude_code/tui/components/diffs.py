from rich.console import RenderableType
from rich.table import Table
from rich.text import Text

from klaude_code.const import DIFF_MAX_RENDER_WIDTH, DIFF_PREFIX_WIDTH, TAB_EXPAND_WIDTH
from klaude_code.protocol.models import DiffFileDiff, DiffLine, DiffUIExtra
from klaude_code.tui.components.rich.theme import ThemeKey


def render_structured_diff(ui_extra: DiffUIExtra, show_file_name: bool = False) -> RenderableType:
    files = ui_extra.files
    if not files:
        return Text("")

    show_headers = show_file_name or len(files) > 1
    prefix_width = _prefix_width(files)
    grid = _create_diff_grid(prefix_width)

    for idx, file_diff in enumerate(files):
        if idx > 0:
            grid.add_row("", "")

        if show_headers:
            grid.add_row(*_render_file_header(file_diff, prefix_width))

        for line in file_diff.lines:
            prefix = _make_structured_prefix(line, prefix_width)
            text = _render_structured_line(line)
            row_style = _line_style(line)
            grid.add_row(Text(prefix, row_style or ThemeKey.TOOL_RESULT), text, style=row_style)

    return grid


def _prefix_width(files: list[DiffFileDiff]) -> int:
    max_line_no = 0
    for file_diff in files:
        for line in file_diff.lines:
            line_no = line.old_line_no if line.kind == "remove" else line.new_line_no
            if line_no is not None:
                max_line_no = max(max_line_no, line_no)
    return max(DIFF_PREFIX_WIDTH, len(str(max_line_no)))


def _create_diff_grid(prefix_width: int) -> Table:
    grid = Table.grid(padding=(0, 0), expand=True)
    grid.width = DIFF_MAX_RENDER_WIDTH
    grid.add_column(no_wrap=True, width=prefix_width + 2)
    grid.add_column(ratio=1, overflow="fold")
    return grid


def _render_file_header(file_diff: DiffFileDiff, prefix_width: int) -> tuple[Text, Text]:
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

    prefix = Text(f"{file_mark:>{prefix_width}}  ", style=ThemeKey.DIFF_FILE_NAME)
    return prefix, file_line


def _make_structured_prefix(line: DiffLine, width: int) -> str:
    if line.kind == "gap":
        return f"{'⋮':>{width}}  "
    number = " " * width
    line_no = line.old_line_no if line.kind == "remove" else line.new_line_no
    if line_no is not None:
        number = f"{line_no:>{width}}"
    marker = "+" if line.kind == "add" else "-" if line.kind == "remove" else " "
    return f"{number} {marker}"


def _render_structured_line(line: DiffLine) -> Text:
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


def _line_style(line: DiffLine) -> ThemeKey | None:
    if line.kind == "add":
        return ThemeKey.DIFF_ADD
    if line.kind == "remove":
        return ThemeKey.DIFF_REMOVE
    return None
