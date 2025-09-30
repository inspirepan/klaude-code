from rich.console import RenderableType
from rich.text import Text

from codex_mini.ui.theme import ThemeKey


def thinking_prefix() -> Text:
    return Text.from_markup("[not italic]∴[/not italic] Thinking …", style=ThemeKey.THINKING)


def render_thinking_content(content: str, is_bold: bool) -> RenderableType:
    """
    Stateless renderer for streaming thinking content.

    Rules:
    - `is_bold` is the initial bold state for the fragment.
    - Each occurrence of "**" toggles the bold state.
    - Supports any number of "**" markers, including adjacent markers.
    """
    out = Text()

    # Fast path: no markers, render with current state
    if "**" not in content:
        out.append_text(Text(content, style=ThemeKey.THINKING_BOLD if is_bold else ThemeKey.THINKING))
        return out

    # Split by "**" and alternate styles segment by segment
    segments = content.split("**")
    current_bold = is_bold
    for segment in segments:
        style = ThemeKey.THINKING_BOLD if current_bold else ThemeKey.THINKING
        if segment:
            out.append_text(Text(segment, style=style))
        # Toggle after each boundary (even if segment is empty)
        current_bold = not current_bold

    return out
