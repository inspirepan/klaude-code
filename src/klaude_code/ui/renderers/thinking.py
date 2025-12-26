import re

from rich.console import RenderableType
from rich.padding import Padding
from rich.text import Text

from klaude_code import const
from klaude_code.ui.renderers.common import create_grid
from klaude_code.ui.rich.markdown import ThinkingMarkdown
from klaude_code.ui.rich.theme import ThemeKey

# UI markers
THINKING_MESSAGE_MARK = "∴"


def normalize_thinking_content(content: str) -> str:
    """Normalize thinking content for display."""
    text = content.rstrip()

    # Weird case of Gemini 3
    text = text.replace("\\n\\n\n\n", "")

    # Fix OpenRouter OpenAI reasoning formatting where segments like
    # "text**Title**\n\n" lose the blank line between segments.
    # We want: "text\n**Title**\n" so that each bold title starts on
    # its own line and uses a single trailing newline.
    text = re.sub(r"([^\n])(\*\*[^*]+?\*\*)\n\n", r"\1  \n\n\2  \n", text)

    # Remove extra newlines between back-to-back bold titles, eg
    # "**Title1****Title2**" -> "**Title1**\n\n**Title2**".
    text = text.replace("****", "**\n\n**")

    # Compact double-newline after bold so the body text follows
    # directly after the title line, using a markdown line break.
    text = text.replace("**\n\n", "**  \n")

    return text


def render_thinking(content: str, *, code_theme: str, style: str) -> RenderableType | None:
    """Render thinking content as markdown with left mark.

    Returns None if content is empty.
    Note: Caller should push thinking_markdown_theme before printing.
    """
    if len(content.strip()) == 0:
        return None

    grid = create_grid()
    grid.add_row(
        Text(THINKING_MESSAGE_MARK, style=ThemeKey.THINKING),
        Padding(
            ThinkingMarkdown(
                normalize_thinking_content(content),
                code_theme=code_theme,
                style=style,
            ),
            (0, const.MARKDOWN_RIGHT_MARGIN, 0, 0),
        ),
    )
    return grid
