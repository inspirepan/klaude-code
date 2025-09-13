from rich.console import RenderableType
from rich.text import Text

from codex_mini.ui.theme import ThemeKey


def thinking_prefix() -> Text:
    return Text.from_markup("[not italic]✳[/not italic] Thinking …", style=ThemeKey.THINKING)


def render_thinking_content(content: str, is_bold: bool) -> RenderableType:
    """
    Stateless renderer for streaming thinking content.

    Applies markdown-like bold toggling based on current state and '**' markers
    in the fragment, but does not modify or return state.
    """
    out = Text()
    if content.count("**") == 2:
        left_part, middle_part, right_part = content.split("**", maxsplit=2)
        if is_bold:
            out.append_text(Text(left_part, style=ThemeKey.THINKING_BOLD))
            out.append_text(Text(middle_part, style=ThemeKey.THINKING))
            out.append_text(Text(right_part, style=ThemeKey.THINKING_BOLD))
        else:
            out.append_text(Text(left_part, style=ThemeKey.THINKING))
            out.append_text(Text(middle_part, style=ThemeKey.THINKING_BOLD))
            out.append_text(Text(right_part, style=ThemeKey.THINKING))
    elif content.count("**") == 1:
        left_part, right_part = content.split("**", maxsplit=1)
        if is_bold:
            out.append_text(Text(left_part, style=ThemeKey.THINKING_BOLD))
            out.append_text(Text(right_part, style=ThemeKey.THINKING))
        else:
            out.append_text(Text(left_part, style=ThemeKey.THINKING))
            out.append_text(Text(right_part, style=ThemeKey.THINKING_BOLD))
    else:
        out.append_text(Text(content, style=ThemeKey.THINKING_BOLD if is_bold else ThemeKey.THINKING))
    return out
