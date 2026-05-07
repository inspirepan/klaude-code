from rich.console import Group, RenderableType
from rich.padding import Padding
from rich.text import Text

from klaude_code.protocol import events
from klaude_code.protocol.models import TaskFileChange
from klaude_code.tui.components.common import create_grid, format_more_lines_indicator
from klaude_code.tui.components.rich.theme import ThemeKey
from klaude_code.tui.components.tools import render_path

MAX_TASK_FILE_CHANGE_ROWS = 20


def _plural(count: int, singular: str, plural: str | None = None) -> str:
    return singular if count == 1 else plural or f"{singular}s"


def _render_stats(change: TaskFileChange) -> Text:
    stats = Text()
    if change.added > 0:
        stats.append(f"+{change.added}", style=ThemeKey.DIFF_STATS_ADD)
    if change.removed > 0:
        if stats.plain:
            stats.append(" ", style=ThemeKey.METADATA_DIM)
        stats.append(f"-{change.removed}", style=ThemeKey.DIFF_STATS_REMOVE)
    if not stats.plain:
        stats.append("0", style=ThemeKey.METADATA_DIM)
    return stats


def _render_state_symbol(change: TaskFileChange) -> Text:
    if change.deleted:
        return Text("-", style=ThemeKey.DIFF_STATS_REMOVE)
    if change.created:
        return Text("+", style=ThemeKey.DIFF_STATS_ADD)
    return Text("~", style=ThemeKey.METADATA_DIM)


def render_task_file_change_summary(e: events.TaskFileChangeSummaryEvent) -> RenderableType:
    files = e.summary.files
    visible_files = files
    hidden_count = 0
    if len(files) > MAX_TASK_FILE_CHANGE_ROWS:
        visible_files = files[: MAX_TASK_FILE_CHANGE_ROWS - 1]
        hidden_count = len(files) - len(visible_files)

    title = Text.assemble(
        ("FILE CHANGES", ThemeKey.METADATA),
        (" · ", ThemeKey.METADATA_DIM),
        (f"{len(files)} {_plural(len(files), 'file')}", ThemeKey.METADATA_DIM),
    )
    title.stylize("bold", 0, len("FILE CHANGES"))

    grid = create_grid()
    for change in visible_files:
        grid.add_row(
            _render_state_symbol(change),
            Text.assemble(
                render_path(change.path, ThemeKey.METADATA),
                ("  ", ThemeKey.METADATA_DIM),
                _render_stats(change),
            ),
        )
    if hidden_count:
        grid.add_row(Text(" "), Text(format_more_lines_indicator(hidden_count), style=ThemeKey.TOOL_RESULT_TRUNCATED))

    return Padding(Group(title, grid), (1, 1, 1, 2), style=ThemeKey.DIFF_FILE_CHANGES_BACKGROUND, expand=False)
