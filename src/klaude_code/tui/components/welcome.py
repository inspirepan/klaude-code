from __future__ import annotations

from pathlib import Path
from typing import ClassVar

from rich.console import Group, RenderableType
from rich.text import Text
from rich.tree import Tree

from klaude_code.log import is_debug_enabled
from klaude_code.protocol import events
from klaude_code.tui.components.rich.quote import Quote
from klaude_code.tui.components.rich.theme import ThemeKey
from klaude_code.ui.common import format_model_params
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


def _build_grouped_tree(
    title: str,
    groups: list[tuple[str, str]],
) -> Tree:
    """Build a Tree with grouped children (e.g. skills, context)."""
    tree = _RoundedTree(Text(title, style=ThemeKey.WELCOME_HIGHLIGHT), guide_style=ThemeKey.LINES)
    label_width = max(len(label) for label, _ in groups)
    for label, content in groups:
        row = Text()
        row.append(label, style=ThemeKey.WELCOME_SCOPE)
        row.append(" " * (label_width - len(label)), style=ThemeKey.WELCOME_INFO)
        row.append(f" {content}", style=ThemeKey.WELCOME_INFO)
        tree.add(row)
    return tree


def _build_skills_tree(grouped_skills: list[tuple[str, list[str]]]) -> Tree:
    tree = _RoundedTree(Text("skills", style=ThemeKey.WELCOME_HIGHLIGHT), guide_style=ThemeKey.LINES)
    for scope, skills in grouped_skills:
        scope_text = Text()
        scope_text.append(f"[{scope}]", style=ThemeKey.WELCOME_SCOPE)
        for skill in skills:
            scope_text.append(f"\n • {skill}", style=ThemeKey.WELCOME_INFO)
        tree.add(scope_text)
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
        (str(e.llm_config.model_id), ThemeKey.WELCOME_HIGHLIGHT),
        (" @ ", ThemeKey.WELCOME_INFO),
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

    # Context tree: loaded memories
    work_dir = Path(e.work_dir)
    loaded_memories = e.loaded_memories or {}
    memory_items: list[tuple[str, str]] = []
    for scope in ("user", "project"):
        paths = loaded_memories.get(scope) or []
        if paths:
            memory_items.append((f"[{scope}]", ", ".join(_format_memory_path(p, work_dir=work_dir) for p in paths)))
    if memory_items:
        renderables.append(Text())
        renderables.append(_build_grouped_tree("context", memory_items))

    # Skills tree
    loaded_skills = e.loaded_skills or {}
    grouped_skills: list[tuple[str, list[str]]] = []
    for scope in ("user", "project", "system"):
        skills = loaded_skills.get(scope) or []
        if skills:
            grouped_skills.append((scope, skills))
    if grouped_skills:
        renderables.append(Text())
        renderables.append(_build_skills_tree(grouped_skills))

    loaded_skill_warnings = e.loaded_skill_warnings or {}
    warning_items: list[tuple[str, str]] = []
    for scope in ("user", "project", "system"):
        warnings = loaded_skill_warnings.get(scope) or []
        if warnings:
            warning_items.append((f"[{scope}]", " | ".join(warnings)))
    if warning_items:
        label_width = max(len(label) for label, _ in warning_items)
        warning_tree = _RoundedTree(
            Text("skill warnings", style=ThemeKey.WARN_BOLD),
            guide_style=ThemeKey.LINES,
        )
        for label, content in warning_items:
            row = Text()
            row.append(label, style=ThemeKey.WARN_SCOPE)
            row.append(" " * (label_width - len(label)), style=ThemeKey.WARN)
            row.append(f" {content}", style=ThemeKey.WARN)
            warning_tree.add(row)
        renderables.append(Text())
        renderables.append(warning_tree)

    border_style = ThemeKey.WELCOME_DEBUG_BORDER if debug_mode else ThemeKey.LINES
    panel_content = Quote(Group(*renderables), style=border_style, prefix="▌ ")

    if e.show_klaude_code_info:
        return Group("", panel_content, "")
    return Group(panel_content, "")
