from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
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


class _RoundedTree(Tree):
    TREE_GUIDES: ClassVar[list[tuple[str, str, str, str]]] = [
        ("    ", "│   ", "├── ", "╰── "),
        ("    ", "│   ", "├── ", "╰── "),
        ("    ", "│   ", "├── ", "╰── "),
    ]


_LABEL_WIDTH = len("[project]")


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


def _get_version() -> str:
    """Get the current version of klaude-code."""
    try:
        return version("klaude-code")
    except PackageNotFoundError:
        return "unknown"


def _build_grouped_tree(
    title: str,
    groups: list[tuple[str, str]],
) -> Tree:
    """Build a Tree with grouped children (e.g. skills, context)."""
    tree = _RoundedTree(Text(title, style=ThemeKey.WELCOME_HIGHLIGHT), guide_style=ThemeKey.LINES)
    for label, content in groups:
        tree.add(Text(f"{label.ljust(_LABEL_WIDTH)} {content}", style=ThemeKey.WELCOME_INFO))
    return tree


def render_welcome(e: events.WelcomeEvent) -> RenderableType:
    """Render the welcome panel with model info and settings."""
    debug_mode = is_debug_enabled()
    renderables: list[RenderableType] = []

    if e.show_klaude_code_info:
        klaude_code_style = ThemeKey.WELCOME_DEBUG_TITLE if debug_mode else ThemeKey.WELCOME_HIGHLIGHT_BOLD
        renderables.append(
            Text.assemble(("Klaude Code", klaude_code_style), (f" v{_get_version()}", ThemeKey.WELCOME_INFO))
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
    skill_items: list[tuple[str, str]] = []
    for scope in ("user", "project", "system"):
        skills = loaded_skills.get(scope) or []
        if skills:
            skill_items.append((f"[{scope}]", ", ".join(skills)))
    if skill_items:
        renderables.append(Text())
        renderables.append(_build_grouped_tree("skills", skill_items))

    border_style = ThemeKey.WELCOME_DEBUG_BORDER if debug_mode else ThemeKey.LINES
    panel_content = Quote(Group(*renderables), style=border_style, prefix="▌ ")

    if e.show_klaude_code_info:
        return Group("", panel_content, "")
    return Group(panel_content, "")
