from rich.console import Group, RenderableType
from rich.table import Table
from rich.text import Text

from klaude_code.config.formatters import format_number
from klaude_code.protocol import events
from klaude_code.protocol.models import ContextCategoryKey, ContextUsageUIExtra
from klaude_code.tui.components.rich.theme import ThemeKey

_GRID_COLUMNS = 20
_GRID_ROWS = 10
_GRID_CELLS = _GRID_COLUMNS * _GRID_ROWS

_FILLED = "⛁"  # ⛁ occupied
_EMPTY = "⛶"  # ⛶ free

_CATEGORY_STYLES: dict[ContextCategoryKey, ThemeKey] = {
    "system_prompt": ThemeKey.CONTEXT_SYSTEM_PROMPT,
    "system_tools": ThemeKey.CONTEXT_SYSTEM_TOOLS,
    "memory": ThemeKey.CONTEXT_MEMORY,
    "skills": ThemeKey.CONTEXT_SKILLS,
    "messages": ThemeKey.CONTEXT_MESSAGES,
    "autocompact_reserve": ThemeKey.CONTEXT_RESERVE,
    "free": ThemeKey.CONTEXT_FREE,
}


def _percent(tokens: int, limit: int) -> float:
    if limit <= 0:
        return 0.0
    return tokens / limit * 100


def _allocate_cells(usage: ContextUsageUIExtra) -> list[ContextCategoryKey]:
    """Assign occupied grid cells to categories, largest-remainder style.

    Only as many cells as the occupied share of the window are handed out -- the rest of the
    grid stays empty. Cells are split strictly in proportion, so on a mostly-empty window a
    category too small to earn a cell shows up in the legend but not in the grid.
    """
    occupied = [category for category in usage.categories if category.key != "free" and category.tokens > 0]
    if not occupied:
        return []

    limit = usage.context_limit
    if limit <= 0:
        # No known window: the grid can only convey relative shares, so fill it entirely.
        budget = _GRID_CELLS
    else:
        occupied_tokens = sum(category.tokens for category in occupied)
        budget = min(_GRID_CELLS, round(occupied_tokens / limit * _GRID_CELLS))
    if budget <= 0:
        return []

    total_tokens = sum(category.tokens for category in occupied)
    exact = [(category.key, category.tokens / total_tokens * budget) for category in occupied]

    # Give every category its floor, then hand the remaining cells to the largest fractions.
    counts: dict[ContextCategoryKey, int] = {key: int(share) for key, share in exact}
    by_largest_fraction = sorted(exact, key=lambda item: -(item[1] - int(item[1])))
    for key, _ in by_largest_fraction:
        if sum(counts.values()) >= budget:
            break
        counts[key] += 1

    cells: list[ContextCategoryKey] = []
    for category in occupied:
        cells.extend([category.key] * counts.get(category.key, 0))
    return cells[:budget]


def _render_grid_rows(usage: ContextUsageUIExtra) -> list[Text]:
    cells = _allocate_cells(usage)
    rows: list[Text] = []
    for row_index in range(_GRID_ROWS):
        row = Text()
        for column_index in range(_GRID_COLUMNS):
            index = row_index * _GRID_COLUMNS + column_index
            if column_index:
                row.append(" ")
            if index < len(cells):
                row.append(_FILLED, style=_CATEGORY_STYLES[cells[index]])
            else:
                row.append(_EMPTY, style=ThemeKey.CONTEXT_FREE)
        rows.append(row)
    return rows


def _render_side_lines(usage: ContextUsageUIExtra) -> list[Text]:
    limit = usage.context_limit
    lines: list[Text] = [
        Text(usage.model_name, style=ThemeKey.SESSION_STATUS_BOLD),
        Text(usage.model_id, style=ThemeKey.CONTEXT_FREE),
    ]

    if limit > 0:
        total = Text(
            f"{format_number(usage.used_tokens)}/{format_number(limit)} tokens",
            style=ThemeKey.SESSION_STATUS,
        )
        total.append(f" ({usage.usage_percent:.1f}%)", style=ThemeKey.CONTEXT_FREE)
    else:
        total = Text(f"{format_number(usage.used_tokens)} tokens", style=ThemeKey.SESSION_STATUS)
    lines.append(total)
    lines.append(Text())

    heading = "Usage by category" if usage.is_calibrated else "Estimated usage by category"
    lines.append(Text(heading, style=ThemeKey.SESSION_STATUS_BOLD))

    for category in usage.categories:
        glyph = _EMPTY if category.key == "free" else _FILLED
        line = Text()
        line.append(f"{glyph} ", style=_CATEGORY_STYLES[category.key])
        line.append(f"{category.label}: ", style=ThemeKey.SESSION_STATUS)
        line.append(f"{format_number(category.tokens)} tokens", style=ThemeKey.SESSION_STATUS)
        if limit > 0:
            line.append(f" ({_percent(category.tokens, limit):.1f}%)", style=ThemeKey.CONTEXT_FREE)
        lines.append(line)

    return lines


def _render_details(usage: ContextUsageUIExtra) -> list[RenderableType]:
    blocks: list[RenderableType] = []
    for section in usage.details:
        header = Text()
        header.append(section.label, style=ThemeKey.SESSION_STATUS_BOLD)
        count = len(section.entries)
        noun = section.hint or "item"
        header.append(
            f" · {count} {noun}{'s' if count != 1 else ''} · {format_number(sum(e.tokens for e in section.entries))} tokens",
            style=ThemeKey.CONTEXT_FREE,
        )
        blocks.append(Text())
        blocks.append(header)

        # Right-align the counts into their own column so entries are easy to compare.
        rows = Table.grid(padding=(0, 2))
        rows.add_column(overflow="fold")
        rows.add_column(justify="right", no_wrap=True)
        for entry in section.entries:
            rows.add_row(
                Text(f"  {entry.name}", style=ThemeKey.SESSION_STATUS),
                Text(format_number(entry.tokens), style=ThemeKey.CONTEXT_FREE),
            )
        blocks.append(rows)
    return blocks


def render_context_usage(e: events.ContextUsageEvent) -> RenderableType:
    """Render context-window usage as a proportional grid plus a category breakdown."""
    usage = e.usage

    layout = Table.grid(padding=(0, 3))
    layout.add_column(overflow="fold")
    layout.add_column(overflow="fold")

    grid_rows = _render_grid_rows(usage)
    side_lines = _render_side_lines(usage)
    for index in range(max(len(grid_rows), len(side_lines))):
        left = grid_rows[index] if index < len(grid_rows) else Text()
        right = side_lines[index] if index < len(side_lines) else Text()
        layout.add_row(left, right)

    blocks: list[RenderableType] = [Text("Context Usage", style=ThemeKey.SESSION_STATUS_BOLD), Text(), layout]
    blocks.extend(_render_details(usage))

    if not usage.is_calibrated:
        blocks.append(Text())
        blocks.append(
            Text(
                "Estimated locally; will be calibrated against real usage after the next response.",
                style=ThemeKey.CONTEXT_FREE,
            )
        )

    return Group(*blocks)
