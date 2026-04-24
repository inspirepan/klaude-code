from __future__ import annotations

import shutil
from pathlib import Path
from typing import ClassVar

from rich.console import Group, RenderableType
from rich.text import Text
from rich.tree import Tree

from klaude_code.config.formatters import format_model_params
from klaude_code.log import is_debug_enabled
from klaude_code.protocol import events
from klaude_code.tui.components.common import create_grid
from klaude_code.tui.components.rich.quote import Quote
from klaude_code.tui.components.rich.theme import ThemeKey
from klaude_code.update import get_display_version


class _RoundedTree(Tree):
    TREE_GUIDES: ClassVar[list[tuple[str, str, str, str]]] = [
        ("    ", "│   ", "├── ", "╰── "),
        ("    ", "│   ", "├── ", "╰── "),
        ("    ", "│   ", "├── ", "╰── "),
    ]


def _format_memory_path(path: str, *, work_dir: Path) -> str:
    """Format memory path for display - show relative path or ~ for home."""
    p = Path(path)
    try:
        return str(p.relative_to(work_dir))
    except ValueError:
        pass
    try:
        return f"~/{p.relative_to(Path.home())}"
    except ValueError:
        return path


def _shorten_warning_path(warning: str, work_dir: Path) -> str:
    """Shorten absolute paths in warning messages for display.

    Extracts the path prefix (before first ': ') and shortens it:
    - Strips everything up to and including '/skills/' to show just '<skill-dir>/SKILL.md'
    - Falls back to relative path or ~ notation
    """
    if "\n" in warning:
        return warning

    sep = ": "
    idx = warning.find(sep)
    if idx < 0:
        return warning
    path_str, message = warning[:idx], warning[idx:]
    # Try to extract just the skill directory name (e.g. "my-skill")
    skills_marker = "/skills/"
    marker_idx = path_str.rfind(skills_marker)
    if marker_idx >= 0:
        short = path_str[marker_idx + len(skills_marker) :]
        # Strip trailing /SKILL.md since all skills use the same filename
        if short.endswith("/SKILL.md"):
            short = short[: -len("/SKILL.md")]
        return short + message
    return _format_memory_path(path_str, work_dir=work_dir) + message


def _parse_duplicate_warning(warning: str) -> tuple[str, list[tuple[str, str, bool]]] | None:
    lines = warning.splitlines()
    if len(lines) != 3 or not lines[0].startswith('duplicate "') or not lines[0].endswith('" skill:'):
        return None

    name = lines[0][len('duplicate "') : -len('" skill:')]
    items: list[tuple[str, str, bool]] = []
    for line in lines[1:]:
        if not line.startswith("- ["):
            return None
        scope_end = line.find("] ")
        if scope_end < 0:
            return None
        scope = line[3:scope_end]
        item = line[scope_end + 2 :]
        using_this = item.endswith(" (using this)")
        if using_this:
            item = item[: -len(" (using this)")]
        items.append((scope, item, using_this))
    return name, items


def _parse_name_mismatch_warning(warning: str) -> tuple[str, str, str, str] | None:
    lines = warning.splitlines()
    if len(lines) != 2 or not lines[0].startswith('skill name "') or not lines[0].endswith('":'):
        return None

    rest = lines[0][len('skill name "') :]
    sep = '" should match directory name "'
    idx = rest.find(sep)
    if idx < 0:
        return None

    skill_name = rest[:idx]
    directory_name = rest[idx + len(sep) : -2]

    line = lines[1]
    if not line.startswith("- ["):
        return None
    scope_end = line.find("] ")
    if scope_end < 0:
        return None

    scope = line[3:scope_end]
    path = line[scope_end + 2 :]
    return skill_name, directory_name, scope, path


def _render_warning(warning: str, *, work_dir: Path) -> RenderableType:
    mismatch = _parse_name_mismatch_warning(warning)
    if mismatch is not None:
        skill_name, directory_name, scope, path = mismatch
        title = Text()
        title.append('skill name "', style=ThemeKey.WARN)
        title.append(skill_name, style=ThemeKey.WARN_BOLD)
        title.append('" should match directory name "', style=ThemeKey.WARN)
        title.append(directory_name, style=ThemeKey.WARN_BOLD)
        title.append('":', style=ThemeKey.WARN)

        paths_grid = create_grid()
        path_text = Text()
        path_text.append(f"[{scope}]", style=ThemeKey.WARN_SCOPE)
        path_text.append(" ", style=ThemeKey.WARN)
        path_text.append(_format_memory_path(path, work_dir=work_dir), style=ThemeKey.WARN)
        paths_grid.add_row(Text("  •", style=ThemeKey.WARN_BOLD), path_text)
        return Group(title, paths_grid)

    duplicate = _parse_duplicate_warning(warning)
    if duplicate is not None:
        name, items = duplicate
        title = Text()
        title.append('duplicate "', style=ThemeKey.WARN)
        title.append(name, style=ThemeKey.WARN_BOLD)
        title.append('" skill:', style=ThemeKey.WARN)
        paths_grid = create_grid()
        for scope, path, using_this in items:
            path_text = Text()
            path_text.append(f"[{scope}]", style=ThemeKey.WARN_SCOPE)
            path_text.append(" ", style=ThemeKey.WARN)
            path_text.append(_format_memory_path(path, work_dir=work_dir), style=ThemeKey.WARN)
            if using_this:
                path_text.append(" (using this)", style=ThemeKey.WARN)
            paths_grid.add_row(Text("  •", style=ThemeKey.WARN_BOLD), path_text)
        return Group(title, paths_grid)

    lines = _shorten_warning_path(warning, work_dir).splitlines() or [warning]
    text = Text(lines[0], style=ThemeKey.WARN)
    for line in lines[1:]:
        text.append("\n")
        text.append(line, style=ThemeKey.WARN)
    return text


def _build_multi_column_tree(
    title: str,
    grouped_items: list[tuple[str, list[str]]],
) -> Tree:
    """Build a Tree with grouped children displayed in multi-column layout."""
    tree = _RoundedTree(Text(title, style=ThemeKey.WELCOME_HIGHLIGHT), guide_style=ThemeKey.LINES)
    # 12 = quote prefix (3) + tree guide indent (4) + margin (3) + item indent (2)
    content_width = shutil.get_terminal_size().columns - 12
    sep = " | "
    for scope, items in grouped_items:
        max_name_width = max(len(item) for item in items)
        num_cols = min(4, max(1, (content_width + len(sep)) // (max_name_width + len(sep))))
        # Compute per-column max widths for this group
        col_widths = [0] * num_cols
        for i, item in enumerate(items):
            col_widths[i % num_cols] = max(col_widths[i % num_cols], len(item))
        scope_text = Text()
        scope_text.append(scope, style=ThemeKey.WELCOME_SCOPE)
        for i, item in enumerate(items):
            col = i % num_cols
            if col == 0:
                scope_text.append("\n")
                scope_text.append("  ", style=ThemeKey.WELCOME_INFO)
            else:
                scope_text.append(sep, style=ThemeKey.LINES)
            is_last_in_row = (col == num_cols - 1) or (i == len(items) - 1)
            if is_last_in_row:
                scope_text.append(item, style=ThemeKey.WELCOME_INFO)
            else:
                scope_text.append(f"{item:<{col_widths[col]}}", style=ThemeKey.WELCOME_INFO)
        tree.add(scope_text)
    return tree


def _build_update_tree(update_info: events.WelcomeUpdateInfo) -> Tree:
    title_style = ThemeKey.WARN_BOLD if update_info.level == "warn" else ThemeKey.WELCOME_HIGHLIGHT
    body_style = ThemeKey.WARN if update_info.level == "warn" else ThemeKey.WELCOME_INFO
    tree = _RoundedTree(Text("update", style=title_style), guide_style=ThemeKey.LINES)
    tree.add(Text(update_info.message, style=body_style))
    return tree


def _build_shortcuts_tree() -> Tree:
    tree = _RoundedTree(Text("shortcuts", style=ThemeKey.WELCOME_HIGHLIGHT), guide_style=ThemeKey.LINES)
    prefix_items = [
        ("@", "files"),
        ("/", "commands"),
        ("//", "skills"),
        ("!", "shell"),
    ]
    prefix_row = Text()
    for i, (key, desc) in enumerate(prefix_items):
        if i > 0:
            prefix_row.append(" · ", style=ThemeKey.LINES)
        prefix_row.append(key, style=ThemeKey.WELCOME_SHORTCUT)
        prefix_row.append(f" {desc}", style=ThemeKey.WELCOME_INFO)
    tree.add(prefix_row)
    key_items = [
        ("ctrl-l", "change model (this chat)"),
        ("ctrl-t", "change thinking level"),
        ("ctrl-v", "paste image"),
    ]
    for key, desc in key_items:
        row = Text()
        row.append(key, style=ThemeKey.WELCOME_SHORTCUT)
        row.append(f" {desc}", style=ThemeKey.WELCOME_INFO)
        tree.add(row)
    return tree


def render_welcome(e: events.WelcomeEvent) -> RenderableType:
    """Render the welcome panel with model info and settings."""
    debug_mode = is_debug_enabled()
    renderables: list[RenderableType] = []

    if e.show_klaude_code_info:
        klaude_code_style = ThemeKey.WELCOME_DEBUG_TITLE if debug_mode else ThemeKey.WELCOME_HIGHLIGHT_BOLD
        renderables.append(
            Text.assemble(("Klaude Code", klaude_code_style), (f" v{get_display_version()}", ThemeKey.WELCOME_INFO))
        )

    # Model tree: model @ provider with params as children
    model_label = Text.assemble(
        (str(e.llm_config.model_id), ThemeKey.WELCOME_INFO_BOLD),
        (" via ", ThemeKey.WELCOME_INFO),
        (e.llm_config.provider_name, ThemeKey.WELCOME_INFO),
    )
    param_strings = format_model_params(e.llm_config)
    if param_strings:
        model_tree = _RoundedTree(model_label, guide_style=ThemeKey.LINES)
        for param_str in param_strings:
            model_tree.add(Text(param_str, style=ThemeKey.WELCOME_INFO))
        renderables.append(model_tree)
    else:
        renderables.append(model_label)

    if e.startup_info is not None:
        if e.startup_info.update_info is not None:
            renderables.append(Text())
            renderables.append(_build_update_tree(e.startup_info.update_info))
        renderables.append(Text())
        renderables.append(_build_shortcuts_tree())

    # Context tree: loaded memories and skills
    work_dir = Path(e.work_dir)
    loaded_memories = e.loaded_memories or {}
    grouped_context: list[tuple[str, list[str]]] = []
    for scope in ("user", "project"):
        paths = loaded_memories.get(scope) or []
        if paths:
            grouped_context.append((f"{scope} memory", [_format_memory_path(p, work_dir=work_dir) for p in paths]))

    loaded_skills = e.loaded_skills or {}
    for scope in ("user", "project", "system"):
        skills = loaded_skills.get(scope) or []
        if skills:
            grouped_context.append((f"{scope} skills", skills))

    if grouped_context:
        renderables.append(Text())
        renderables.append(_build_multi_column_tree("context", grouped_context))

    loaded_skill_warnings = e.loaded_skill_warnings or {}
    warning_items: list[str] = []
    for scope in ("user", "project", "system"):
        warnings = loaded_skill_warnings.get(scope) or []
        if warnings:
            warning_items.extend(warnings)
    if warning_items:
        warning_tree = _RoundedTree(
            Text("skill warnings", style=ThemeKey.WARN_BOLD),
            guide_style=ThemeKey.LINES,
        )
        for warning in warning_items:
            warning_tree.add(_render_warning(warning, work_dir=work_dir))
        renderables.append(Text())
        renderables.append(warning_tree)

    border_style = ThemeKey.WELCOME_DEBUG_BORDER if debug_mode else ThemeKey.LINES
    panel_content = Quote(Group(*renderables), style=border_style, prefix="▌ ")

    if e.show_klaude_code_info:
        return Group("", panel_content, "")
    return Group(panel_content, "")
