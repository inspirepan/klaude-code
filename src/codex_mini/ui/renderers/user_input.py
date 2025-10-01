import re

from rich.console import Group, RenderableType
from rich.text import Text

from codex_mini.protocol.commands import CommandName
from codex_mini.ui.base.theme import ThemeKey
from codex_mini.ui.rich_ext.quote import Quote


def render_at_pattern(
    text: str,
    at_style: str = ThemeKey.USER_INPUT_AT_PATTERN,
    other_style: str = ThemeKey.USER_INPUT,
) -> Text:
    if "@" in text:
        parts = re.split(r"(\s+)", text)
        result = Text("")
        for s in parts:
            if s.startswith("@"):
                result.append_text(Text(s, at_style))
            else:
                result.append_text(Text(s, other_style))
        return result
    return Text(text, style=other_style)


def _is_valid_slash_command(command: str) -> bool:
    try:
        CommandName(command)
        return True
    except ValueError:
        return False


def render_user_input(content: str) -> RenderableType:
    """Render a user message as a group of quoted lines with styles.

    - Highlights slash command on the first line if recognized
    - Highlights @file patterns in all lines
    """
    lines = content.split("\n")
    renderables: list[RenderableType] = []
    for i, line in enumerate(lines):
        line_text = render_at_pattern(line)

        if i == 0 and line.startswith("/"):
            splits = line.split(" ", maxsplit=1)
            if _is_valid_slash_command(splits[0][1:]):
                if len(splits) <= 1:
                    renderables.append(Text(f" {line} ", style=ThemeKey.USER_INPUT_SLASH_COMMAND))
                    continue
                else:
                    line_text = Text.assemble(
                        (f" {splits[0]} ", ThemeKey.USER_INPUT_SLASH_COMMAND),
                        " ",
                        render_at_pattern(splits[1]),
                    )
                    renderables.append(line_text)
                    continue

        renderables.append(Quote(line_text, style=ThemeKey.USER_INPUT))
    return Group(*renderables)


def render_interrupt() -> RenderableType:
    return Text(" INTERRUPTED \n", style=ThemeKey.INTERRUPT)
