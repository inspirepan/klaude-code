from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from rich.console import Group, RenderableType
from rich.text import Text

from klaude_code.log import is_debug_enabled
from klaude_code.protocol import events
from klaude_code.tui.components.rich.quote import Quote
from klaude_code.tui.components.rich.theme import ThemeKey
from klaude_code.ui.common import format_model_params


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


def render_welcome(e: events.WelcomeEvent) -> RenderableType:
    """Render the welcome panel with model info and settings.

    Args:
        e: The welcome event.
    """
    debug_mode = is_debug_enabled()

    panel_content = Text()

    if e.show_klaude_code_info:
        # First line: Klaude Code version
        klaude_code_style = ThemeKey.WELCOME_DEBUG_TITLE if debug_mode else ThemeKey.WELCOME_HIGHLIGHT_BOLD
        panel_content.append_text(Text("Klaude Code", style=klaude_code_style))
        panel_content.append_text(Text(f" v{_get_version()}", style=ThemeKey.WELCOME_INFO))
        panel_content.append_text(Text("\n"))

    # Model line: model @ provider · params...
    panel_content.append_text(
        Text.assemble(
            (str(e.llm_config.model_id), ThemeKey.WELCOME_HIGHLIGHT),
            (" @ ", ThemeKey.WELCOME_INFO),
            (e.llm_config.provider_name, ThemeKey.WELCOME_INFO),
        )
    )

    # Use format_model_params for consistent formatting
    param_strings = format_model_params(e.llm_config)

    # Render config items with tree-style prefixes
    for i, param_str in enumerate(param_strings):
        is_last = i == len(param_strings) - 1
        prefix = "╰─ " if is_last else "├─ "
        panel_content.append_text(
            Text.assemble(
                ("\n", ThemeKey.WELCOME_INFO),
                (prefix, ThemeKey.LINES),
                (param_str, ThemeKey.WELCOME_INFO),
            )
        )

    # Loaded memories summary
    work_dir = Path(e.work_dir)
    loaded_memories = e.loaded_memories or {}
    user_memories = loaded_memories.get("user") or []
    project_memories = loaded_memories.get("project") or []

    memory_groups: list[tuple[str, list[str]]] = []
    if user_memories:
        memory_groups.append(("user", user_memories))
    if project_memories:
        memory_groups.append(("project", project_memories))

    if memory_groups:
        panel_content.append_text(Text("\n\n", style=ThemeKey.WELCOME_INFO))
        panel_content.append_text(Text("context", style=ThemeKey.WELCOME_HIGHLIGHT))

        label_width = len("[project]")

        for i, (group_name, paths) in enumerate(memory_groups):
            is_last = i == len(memory_groups) - 1
            prefix = "╰─ " if is_last else "├─ "
            label = f"[{group_name}]"
            formatted_paths = ", ".join(_format_memory_path(p, work_dir=work_dir) for p in paths)
            panel_content.append_text(
                Text.assemble(
                    ("\n", ThemeKey.WELCOME_INFO),
                    (prefix, ThemeKey.LINES),
                    (f"{label.ljust(label_width)} {formatted_paths}", ThemeKey.WELCOME_INFO),
                )
            )

    # Loaded skills summary is provided by core via WelcomeEvent to keep TUI decoupled.
    loaded_skills = e.loaded_skills or {}
    user_skills = loaded_skills.get("user") or []
    project_skills = loaded_skills.get("project") or []
    system_skills = loaded_skills.get("system") or []

    skill_groups: list[tuple[str, list[str]]] = []
    if user_skills:
        skill_groups.append(("user", user_skills))
    if project_skills:
        skill_groups.append(("project", project_skills))
    if system_skills:
        skill_groups.append(("system", system_skills))

    if skill_groups:
        panel_content.append_text(Text("\n\n", style=ThemeKey.WELCOME_INFO))
        panel_content.append_text(Text("skills", style=ThemeKey.WELCOME_HIGHLIGHT))

        label_width = len("[project]")

        for i, (group_name, skills) in enumerate(skill_groups):
            is_last = i == len(skill_groups) - 1
            prefix = "╰─ " if is_last else "├─ "
            label = f"[{group_name}]"
            panel_content.append_text(
                Text.assemble(
                    ("\n", ThemeKey.WELCOME_INFO),
                    (prefix, ThemeKey.LINES),
                    (f"{label.ljust(label_width)} {', '.join(skills)}", ThemeKey.WELCOME_INFO),
                )
            )

    border_style = ThemeKey.WELCOME_DEBUG_BORDER if debug_mode else ThemeKey.LINES

    if e.show_klaude_code_info:
        groups = ["", Quote(panel_content, style=border_style, prefix="▌ "), ""]
    else:
        groups = [Quote(panel_content, style=border_style, prefix="▌ "), ""]
    return Group(*groups)
