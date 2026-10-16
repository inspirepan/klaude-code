from rich.console import Console, ConsoleOptions, RenderableType, RenderResult
from rich.measure import Measurement
from rich.table import Table
from rich.text import Text

from klaude_code.const import DIFF_MAX_RENDER_WIDTH, DIFF_PREFIX_WIDTH, TAB_EXPAND_WIDTH
from klaude_code.protocol.models import DiffFileDiff, DiffLine, DiffUIExtra
from klaude_code.tui.components.rich.theme import ThemeKey

# Folded diffs (until Ctrl+T) show a small change whole and preview a large one.
# Prose reads in bigger pieces than code, so Markdown gets a larger budget.
_FOLD_FULL_MAX_CHANGED = 10
_FOLD_PREVIEW_LINES = 5
_FOLD_DOC_FULL_MAX_CHANGED = 30
FOLD_DOC_PREVIEW_LINES = 15
_DOC_SUFFIXES = (".md", ".markdown", ".mdx")
EXPAND_DIFFS_HINT = "Ctrl+T"


def is_doc_path(path: str) -> bool:
    return path.lower().endswith(_DOC_SUFFIXES)


def fold_limit(file_diff: DiffFileDiff) -> int | None:
    """Lines a folded diff shows for this file, or None to show it whole.

    A new non-doc file shows only its header: rewritten or generated code is
    rarely read line by line, while a few edited lines usually are.
    """
    doc = is_doc_path(file_diff.file_path)
    if file_diff.change_type == "delete":
        return 0
    if file_diff.change_type == "add":
        return FOLD_DOC_PREVIEW_LINES if doc else 0
    changed = file_diff.stats_add + file_diff.stats_remove
    if changed <= (_FOLD_DOC_FULL_MAX_CHANGED if doc else _FOLD_FULL_MAX_CHANGED):
        return None
    return FOLD_DOC_PREVIEW_LINES if doc else _FOLD_PREVIEW_LINES


def render_structured_diff(
    ui_extra: DiffUIExtra,
    show_file_name: bool = False,
    *,
    fold: bool = False,
) -> RenderableType:
    files = ui_extra.files
    if not files:
        return Text("")

    return _StructuredDiff(files, show_file_name=show_file_name, fold=fold)


class _StructuredDiff:
    def __init__(
        self,
        files: list[DiffFileDiff],
        *,
        show_file_name: bool = False,
        fold: bool = False,
    ):
        self.files = files
        self.show_headers = show_file_name or len(files) > 1
        self.fold = fold
        self.prefix_width = _prefix_width(files)

    def __rich_measure__(self, console: Console, options: ConsoleOptions) -> Measurement:
        max_width = min(DIFF_MAX_RENDER_WIDTH, options.max_width)
        grid = _render_structured_diff_grid(self.files, self.prefix_width, self.show_headers, fold=self.fold)
        return console.measure(grid, options=options.update_width(max_width))

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        max_width = min(DIFF_MAX_RENDER_WIDTH, options.max_width)
        grid = _render_structured_diff_grid(self.files, self.prefix_width, self.show_headers, fold=self.fold)
        grid.width = console.measure(grid, options=options.update_width(max_width)).maximum
        yield grid


def _render_structured_diff_grid(
    files: list[DiffFileDiff],
    prefix_width: int,
    show_headers: bool,
    *,
    fold: bool,
) -> Table:
    grid = _create_diff_grid(prefix_width)

    for idx, file_diff in enumerate(files):
        if idx > 0:
            grid.add_row("", "")

        limit = fold_limit(file_diff) if fold else None
        if show_headers or file_diff.change_type in ("add", "delete") or limit is not None:
            grid.add_row(*_render_file_header(file_diff, prefix_width))

        lines = file_diff.lines
        hidden_lines = 0
        if limit is not None and len(lines) > limit:
            hidden_lines = len(lines) - limit
            lines = lines[:limit]

        for line in lines:
            prefix = _make_structured_prefix(line, prefix_width)
            text = _render_structured_line(line)
            row_style = _line_style(line)
            grid.add_row(Text(prefix, row_style or ThemeKey.TOOL_RESULT), text, style=row_style)

        if hidden_lines:
            grid.add_row(
                Text(f"{'…':>{prefix_width}}  ", style=ThemeKey.TOOL_RESULT_TRUNCATED),
                Text(f"{hidden_lines} more lines · {EXPAND_DIFFS_HINT}", style=ThemeKey.TOOL_RESULT_TRUNCATED),
            )

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
    grid = Table.grid(padding=(0, 0))
    grid.add_column(no_wrap=True, width=prefix_width + 2)
    grid.add_column(overflow="fold")
    return grid


def _render_file_header(file_diff: DiffFileDiff, prefix_width: int) -> tuple[Text, Text]:
    file_text = Text(file_diff.file_path, style=ThemeKey.DIFF_FILE_NAME)
    stats_text = Text()
    if file_diff.change_type == "add" or file_diff.stats_add > 0:
        stats_text.append(f"+{file_diff.stats_add}", style=ThemeKey.DIFF_STATS_ADD)
    if file_diff.change_type == "delete" or file_diff.stats_remove > 0:
        if stats_text.plain:
            stats_text.append(" ")
        stats_text.append(f"-{file_diff.stats_remove}", style=ThemeKey.DIFF_STATS_REMOVE)

    file_line = Text(style=ThemeKey.DIFF_FILE_NAME)
    file_line.append_text(file_text)
    if stats_text.plain:
        file_line.append(" (")
        file_line.append_text(stats_text)
        file_line.append(")")

    if file_diff.change_type == "add":
        file_mark = "+"
    elif file_diff.change_type == "delete":
        file_mark = "-"
    elif file_diff.stats_add > 0 and file_diff.stats_remove == 0:
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
    text = Text(overflow="ellipsis", no_wrap=True) if line.kind == "ctx" else Text()
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
