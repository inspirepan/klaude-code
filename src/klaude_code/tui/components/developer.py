from rich.console import Group, RenderableType
from rich.text import Text

from klaude_code.protocol import events
from klaude_code.protocol.models import (
    AtFileImagesUIItem,
    AtFileOpsUIItem,
    ExternalFileChangesUIItem,
    MemoryLoadedUIItem,
    PasteFilesUIItem,
    SkillActivatedUIItem,
    SkillDiscoveredUIItem,
    SkillListingUIItem,
    TodoAttachmentUIItem,
    UserImagesUIItem,
)
from klaude_code.tui.components.common import create_grid
from klaude_code.tui.components.rich.theme import ThemeKey
from klaude_code.tui.components.tools import render_path

ATTACHMENT_BULLET = "+"


def need_render_developer_message(e: events.DeveloperMessageEvent) -> bool:
    if not e.item.ui_extra:
        return False
    return len(e.item.ui_extra.items) > 0


def _render_available_skills(names: list[str], *, incremental: bool) -> RenderableType:
    grid = create_grid()

    if incremental:
        label = "Updated available skill " if len(names) == 1 else "Updated available skills "
        grid.add_row(
            Text(ATTACHMENT_BULLET, style=ThemeKey.ATTACHMENT),
            Text.assemble(
                (label, ThemeKey.ATTACHMENT),
                Text(", ", ThemeKey.ATTACHMENT).join(Text(name, ThemeKey.ATTACHMENT) for name in names),
            ),
        )
        return grid

    count = len(names)
    grid.add_row(
        Text(ATTACHMENT_BULLET, style=ThemeKey.ATTACHMENT),
        Text(
            f"{count} available skill{'s' if count != 1 else ''}",
            ThemeKey.ATTACHMENT,
        ),
    )
    return grid


def render_developer_message(e: events.DeveloperMessageEvent) -> RenderableType:
    """Render developer message details into a single group.

    Includes: memory paths, skill listings, external file changes, todo attachment, @file operations.
    Command output is excluded; render it separately via `render_command_output`.
    """
    parts: list[RenderableType] = []
    available_skill_names: list[str] = []
    available_skills_incremental = False
    discovered_skill_names: list[str] = []

    if e.item.ui_extra:
        for ui_item in e.item.ui_extra.items:
            match ui_item:
                case MemoryLoadedUIItem() as item:
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
                case ExternalFileChangesUIItem() as item:
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
                case TodoAttachmentUIItem() as item:
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
                case AtFileOpsUIItem() as item:
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
                case UserImagesUIItem() as item:
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
                case SkillActivatedUIItem() as item:
                    grid = create_grid()
                    grid.add_row(
                        Text(ATTACHMENT_BULLET, style=ThemeKey.ATTACHMENT),
                        Text.assemble(
                            ("Activated skill ", ThemeKey.ATTACHMENT),
                            (item.name, ThemeKey.TOOL_PARAM_FILE_PATH_SKILL_NAME),
                        ),
                    )
                    parts.append(grid)
                case SkillListingUIItem() as item:
                    available_skills_incremental = available_skills_incremental or item.incremental
                    for name in item.names:
                        if name not in available_skill_names:
                            available_skill_names.append(name)
                case SkillDiscoveredUIItem() as item:
                    if item.name not in discovered_skill_names:
                        discovered_skill_names.append(item.name)
                case AtFileImagesUIItem():
                    # Image display is handled by renderer.display_developer_message
                    pass
                case PasteFilesUIItem() as item:
                    grid = create_grid()
                    count = len(item.tags)
                    grid.add_row(
                        Text(ATTACHMENT_BULLET, style=ThemeKey.ATTACHMENT),
                        Text(
                            f"Saved {count} paste{'s' if count > 1 else ''} to file",
                            style=ThemeKey.ATTACHMENT,
                        ),
                    )
                    parts.append(grid)

    if available_skill_names:
        parts.append(_render_available_skills(available_skill_names, incremental=available_skills_incremental))

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
