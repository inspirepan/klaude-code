from rich.console import Group, RenderableType
from rich.text import Text

from klaude_code.protocol import events, model
from klaude_code.tui.components.common import create_grid
from klaude_code.tui.components.rich.theme import ThemeKey
from klaude_code.tui.components.tools import render_path

ATTACHMENT_BULLET = "+"


def need_render_developer_message(e: events.DeveloperMessageEvent) -> bool:
    if not e.item.ui_extra:
        return False
    return len(e.item.ui_extra.items) > 0


def render_developer_message(e: events.DeveloperMessageEvent) -> RenderableType:
    """Render developer message details into a single group.

    Includes: memory paths, skill listings, external file changes, todo attachment, @file operations.
    Command output is excluded; render it separately via `render_command_output`.
    """
    parts: list[RenderableType] = []
    available_skill_names: list[str] = []
    discovered_skill_names: list[str] = []

    if e.item.ui_extra:
        for ui_item in e.item.ui_extra.items:
            match ui_item:
                case model.MemoryLoadedUIItem() as item:
                    grid = create_grid()
                    grid.add_row(
                        Text(ATTACHMENT_BULLET, style=ThemeKey.ATTACHMENT),
                        Text.assemble(
                            ("Read memory ", ThemeKey.ATTACHMENT),
                            Text(", ", ThemeKey.ATTACHMENT).join(
                                render_path(mem.path, ThemeKey.ATTACHMENT_BOLD) for mem in item.files
                            ),
                        ),
                    )
                    parts.append(grid)
                case model.ExternalFileChangesUIItem() as item:
                    grid = create_grid()
                    for file_path in item.paths:
                        grid.add_row(
                            Text(ATTACHMENT_BULLET, style=ThemeKey.ATTACHMENT),
                            Text.assemble(
                                ("Read ", ThemeKey.ATTACHMENT),
                                render_path(file_path, ThemeKey.ATTACHMENT_BOLD),
                                (" after external changes", ThemeKey.ATTACHMENT),
                            ),
                        )
                    parts.append(grid)
                case model.TodoAttachmentUIItem() as item:
                    match item.reason:
                        case "not_used_recently":
                            text = "Todo hasn't been updated recently"
                        case "empty":
                            text = "Todo list is empty"
                    grid = create_grid()
                    grid.add_row(
                        Text(ATTACHMENT_BULLET, style=ThemeKey.ATTACHMENT),
                        Text(text, ThemeKey.ATTACHMENT),
                    )
                    parts.append(grid)
                case model.AtFileOpsUIItem() as item:
                    grid = create_grid()
                    grouped: dict[str, list[str]] = {}
                    for op in item.ops:
                        grouped.setdefault(op.operation, []).append(op.path)

                    for operation, paths in grouped.items():
                        path_texts = Text(", ", ThemeKey.ATTACHMENT).join(
                            render_path(p, ThemeKey.ATTACHMENT_BOLD) for p in paths
                        )
                        grid.add_row(
                            Text(ATTACHMENT_BULLET, style=ThemeKey.ATTACHMENT),
                            Text.assemble(
                                (f"{operation} ", ThemeKey.ATTACHMENT),
                                path_texts,
                            ),
                        )
                    parts.append(grid)
                case model.UserImagesUIItem() as item:
                    grid = create_grid()
                    count = item.count
                    grid.add_row(
                        Text(ATTACHMENT_BULLET, style=ThemeKey.ATTACHMENT),
                        Text(
                            f"Attached {count} image{'s' if count > 1 else ''}",
                            style=ThemeKey.ATTACHMENT,
                        ),
                    )
                    parts.append(grid)
                case model.SkillActivatedUIItem() as item:
                    grid = create_grid()
                    grid.add_row(
                        Text(ATTACHMENT_BULLET, style=ThemeKey.ATTACHMENT),
                        Text.assemble(
                            ("Activated skill ", ThemeKey.ATTACHMENT),
                            (item.name, ThemeKey.TOOL_PARAM_FILE_PATH_SKILL_NAME),
                        ),
                    )
                    parts.append(grid)
                case model.SkillListingUIItem() as item:
                    for name in item.names:
                        if name not in available_skill_names:
                            available_skill_names.append(name)
                case model.SkillDiscoveredUIItem() as item:
                    if item.name not in discovered_skill_names:
                        discovered_skill_names.append(item.name)
                case model.AtFileImagesUIItem():
                    # Image display is handled by renderer.display_developer_message
                    pass

    if available_skill_names:
        grid = create_grid()
        count = len(available_skill_names)
        grid.add_row(
            Text(ATTACHMENT_BULLET, style=ThemeKey.ATTACHMENT),
            Text(
                f"{count} available skill{'s' if count != 1 else ''}",
                ThemeKey.ATTACHMENT,
            ),
        )
        parts.append(grid)

    if discovered_skill_names:
        grid = create_grid()
        label = "Discovered skill " if len(discovered_skill_names) == 1 else "Discovered skills "
        grid.add_row(
            Text(ATTACHMENT_BULLET, style=ThemeKey.ATTACHMENT),
            Text.assemble(
                (label, ThemeKey.ATTACHMENT),
                Text(", ", ThemeKey.ATTACHMENT).join(
                    Text(name, ThemeKey.ATTACHMENT) for name in discovered_skill_names
                ),
            ),
        )
        parts.append(grid)

    return Group(*parts) if parts else Text("")
