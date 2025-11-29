from rich.console import RenderableType
from rich.padding import Padding
from rich.text import Text

from klaude_code.ui.rich.markdown import NoInsetMarkdown
from klaude_code.ui.rich.theme import ThemeKey


def thinking_prefix() -> Text:
    return Text.from_markup("[not italic]⸫[/not italic] Thinking …", style=ThemeKey.THINKING)


def _normalize_thinking_content(content: str) -> str:
    """Normalize thinking content for display."""
    return (
        content.rstrip()
        .replace("**\n\n", "**  \n")
        .replace("\\n\\n\n\n", "")  # Weird case of Gemini 3
        .replace("****", "**\n\n**")  # remove extra newlines after bold titles
    )


def render_thinking(content: str, *, code_theme: str, style: str) -> RenderableType | None:
    """Render thinking content as indented markdown.

    Returns None if content is empty.
    Note: Caller should push thinking_markdown_theme before printing.
    """
    if len(content.strip()) == 0:
        return None

    return Padding.indent(
        NoInsetMarkdown(
            _normalize_thinking_content(content),
            code_theme=code_theme,
            style=style,
        ),
        level=2,
    )
