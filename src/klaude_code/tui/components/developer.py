from rich.console import Group, RenderableType
from rich.text import Text

from klaude_code.protocol import events, model
from klaude_code.tui.components.common import create_grid
from klaude_code.tui.components.rich.theme import ThemeKey
from klaude_code.tui.components.tools import render_path

REMINDER_BULLET = "⧉"


def need_render_developer_message(e: events.DeveloperMessageEvent) -> bool:
    if not e.item.ui_extra:
        return False
    return len(e.item.ui_extra.items) > 0


def render_developer_message(e: events.DeveloperMessageEvent) -> RenderableType:
    """Render developer message details into a single group.

    Includes: memory paths, external file changes, todo reminder, @file operations.
    Command output is excluded; render it separately via `render_command_output`.
    """
    parts: list[RenderableType] = []

    if e.item.ui_extra:
        for ui_item in e.item.ui_extra.items:
            match ui_item:
                case model.MemoryLoadedUIItem() as item:
                    grid = create_grid()
                    grid.add_row(
                        Text(REMINDER_BULLET, style=ThemeKey.REMINDER),
                        Text.assemble(
                            ("Load memory ", ThemeKey.REMINDER),
                            Text(", ", ThemeKey.REMINDER).join(
                                render_path(mem.path, ThemeKey.REMINDER_BOLD) for mem in item.files
                            ),
                        ),
                    )
                    parts.append(grid)
                case model.ExternalFileChangesUIItem() as item:
                    grid = create_grid()
                    for file_path in item.paths:
                        grid.add_row(
                            Text(REMINDER_BULLET, style=ThemeKey.REMINDER),
                            Text.assemble(
                                ("Read ", ThemeKey.REMINDER),
                                render_path(file_path, ThemeKey.REMINDER_BOLD),
                                (" after external changes", ThemeKey.REMINDER),
                            ),
                        )
                    parts.append(grid)
                case model.TodoReminderUIItem() as item:
                    match item.reason:
                        case "not_used_recently":
                            text = "Todo hasn't been updated recently"
                        case "empty":
                            text = "Todo list is empty"
                    grid = create_grid()
                    grid.add_row(
                        Text(REMINDER_BULLET, style=ThemeKey.REMINDER),
                        Text(text, ThemeKey.REMINDER),
                    )
                    parts.append(grid)
                case model.AtFileOpsUIItem() as item:
                    grid = create_grid()
                    grouped: dict[tuple[str, str | None], list[str]] = {}
                    for op in item.ops:
                        key = (op.operation, op.mentioned_in)
                        grouped.setdefault(key, []).append(op.path)

                    for (operation, mentioned_in), paths in grouped.items():
                        path_texts = Text(", ", ThemeKey.REMINDER).join(
                            render_path(p, ThemeKey.REMINDER_BOLD) for p in paths
                        )
                        if mentioned_in:
                            grid.add_row(
                                Text(REMINDER_BULLET, style=ThemeKey.REMINDER),
                                Text.assemble(
                                    (f"{operation} ", ThemeKey.REMINDER),
                                    path_texts,
                                    (" mentioned in ", ThemeKey.REMINDER),
                                    render_path(mentioned_in, ThemeKey.REMINDER_BOLD),
                                ),
                            )
                        else:
                            grid.add_row(
                                Text(REMINDER_BULLET, style=ThemeKey.REMINDER),
                                Text.assemble(
                                    (f"{operation} ", ThemeKey.REMINDER),
                                    path_texts,
                                ),
                            )
                    parts.append(grid)
                case model.UserImagesUIItem() as item:
                    grid = create_grid()
                    count = item.count
                    grid.add_row(
                        Text(REMINDER_BULLET, style=ThemeKey.REMINDER),
                        Text(
                            f"Attached {count} image{'s' if count > 1 else ''}",
                            style=ThemeKey.REMINDER,
                        ),
                    )
                    parts.append(grid)
                case model.SkillActivatedUIItem() as item:
                    grid = create_grid()
                    grid.add_row(
                        Text(REMINDER_BULLET, style=ThemeKey.REMINDER),
                        Text.assemble(
                            ("Activated skill ", ThemeKey.REMINDER),
                            (item.name, ThemeKey.REMINDER_BOLD),
                        ),
                    )
                    parts.append(grid)
                case model.AtFileImagesUIItem():
                    # Image display is handled by renderer.display_developer_message
                    pass

    return Group(*parts) if parts else Text("")
