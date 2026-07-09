from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

from rich.console import Group, RenderableType
from rich.text import Text
from rich.tree import Tree

from klaude_code.config.formatters import format_model_params
from klaude_code.log import is_debug_enabled
from klaude_code.protocol import events
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


_SCOPE_PRIORITY = {"system": 0, "user": 1, "project": 2}


@dataclass(frozen=True)
class _DuplicateWarning:
    name: str
    chain: list[tuple[str, str]]


@dataclass(frozen=True)
class _NameMismatchWarning:
    skill_name: str
    directory_name: str
    scope: str
    path: str


type _AggregatedWarning = _DuplicateWarning | _NameMismatchWarning | str


def _shorten_skill_path(path: str, *, work_dir: Path) -> str:
    """Format a skill path for display: ~ / relative, strip trailing /SKILL.md."""
    short = _format_memory_path(path, work_dir=work_dir)
    if short.endswith("/SKILL.md"):
        return short[: -len("/SKILL.md")]
    return short


def _shorten_warning_path(warning: str, work_dir: Path) -> str:
    """Shorten absolute paths in generic (non-structured) warning messages."""
    if "\n" in warning:
        return warning

    sep = ": "
    idx = warning.find(sep)
    if idx < 0:
        return warning
    path_str, message = warning[:idx], warning[idx:]
    return _shorten_skill_path(path_str, work_dir=work_dir) + message


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


def _merge_duplicate_chain(
    existing: list[tuple[str, str]],
    new_items: list[tuple[str, str, bool]],
) -> list[tuple[str, str]]:
    """Merge a new duplicate pair into an ordered override chain.

    Keeps unique (scope, path) entries in encounter order, then ensures the
    highest-priority scope (project > user > system) is last — that is the
    effective skill.
    """
    seen = {(scope, path) for scope, path in existing}
    merged = list(existing)
    for scope, path, _using in new_items:
        key = (scope, path)
        if key not in seen:
            seen.add(key)
            merged.append(key)

    if len(merged) <= 1:
        return merged

    winner_idx = max(range(len(merged)), key=lambda i: _SCOPE_PRIORITY.get(merged[i][0], -1))
    if winner_idx != len(merged) - 1:
        winner = merged.pop(winner_idx)
        merged.append(winner)
    return merged


def _aggregate_skill_warnings(warning_items: list[str]) -> list[_AggregatedWarning]:
    """Parse warnings and merge same-name duplicates into override chains."""
    result: list[_AggregatedWarning] = []
    dup_index: dict[str, int] = {}

    for warning in warning_items:
        duplicate = _parse_duplicate_warning(warning)
        if duplicate is not None:
            name, items = duplicate
            if name in dup_index:
                idx = dup_index[name]
                existing = result[idx]
                assert isinstance(existing, _DuplicateWarning)
                result[idx] = _DuplicateWarning(name, _merge_duplicate_chain(existing.chain, items))
            else:
                dup_index[name] = len(result)
                result.append(_DuplicateWarning(name, _merge_duplicate_chain([], items)))
            continue

        mismatch = _parse_name_mismatch_warning(warning)
        if mismatch is not None:
            skill_name, directory_name, scope, path = mismatch
            result.append(_NameMismatchWarning(skill_name, directory_name, scope, path))
            continue

        result.append(warning)

    return result


def _append_scoped_path(text: Text, scope: str, path: str, *, work_dir: Path) -> None:
    text.append(f"[{scope}]", style=ThemeKey.WARN_SCOPE)
    text.append(" ", style=ThemeKey.WARN)
    text.append(_shorten_skill_path(path, work_dir=work_dir), style=ThemeKey.WARN)


def _render_duplicate_warning(entry: _DuplicateWarning, *, work_dir: Path) -> Text:
    text = Text()
    text.append(entry.name, style=ThemeKey.WARN_BOLD)
    text.append("  ", style=ThemeKey.WARN)
    for i, (scope, path) in enumerate(entry.chain):
        if i > 0:
            text.append(" → ", style=ThemeKey.WARN)
        _append_scoped_path(text, scope, path, work_dir=work_dir)
    return text


def _render_name_mismatch_warning(entry: _NameMismatchWarning, *, work_dir: Path) -> Text:
    text = Text()
    text.append(entry.skill_name, style=ThemeKey.WARN_BOLD)
    text.append(" ≠ ", style=ThemeKey.WARN)
    text.append(entry.directory_name, style=ThemeKey.WARN_BOLD)
    text.append("  ", style=ThemeKey.WARN)
    _append_scoped_path(text, entry.scope, entry.path, work_dir=work_dir)
    return text


def _render_generic_warning(warning: str, *, work_dir: Path) -> Text:
    lines = _shorten_warning_path(warning, work_dir).splitlines() or [warning]
    text = Text(lines[0], style=ThemeKey.WARN)
    for line in lines[1:]:
        text.append("\n")
        text.append(line, style=ThemeKey.WARN)
    return text


def _render_aggregated_warning(entry: _AggregatedWarning, *, work_dir: Path) -> Text:
    if isinstance(entry, _DuplicateWarning):
        return _render_duplicate_warning(entry, work_dir=work_dir)
    if isinstance(entry, _NameMismatchWarning):
        return _render_name_mismatch_warning(entry, work_dir=work_dir)
    return _render_generic_warning(entry, work_dir=work_dir)


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
        for entry in _aggregate_skill_warnings(warning_items):
            warning_tree.add(_render_aggregated_warning(entry, work_dir=work_dir))
        renderables.append(Text())
        renderables.append(warning_tree)

    border_style = ThemeKey.WELCOME_DEBUG_BORDER if debug_mode else ThemeKey.LINES
    panel_content = Quote(Group(*renderables), style=border_style, prefix="▌ ")

    if e.show_klaude_code_info:
        return Group("", panel_content, "")
    return Group(panel_content, "")
