import re

from rich.console import Group, RenderableType
from rich.text import Text

from klaude_code.command import is_slash_command_name
from klaude_code.ui.renderers.common import create_grid
from klaude_code.ui.rich.theme import ThemeKey

# Match @-file patterns only when they appear at the beginning of the line
# or immediately after whitespace, to avoid treating mid-word email-like
# patterns such as foo@bar.com as file references.
AT_FILE_RENDER_PATTERN = re.compile(r'(?<!\S)@("([^"]+)"|\S+)')


def render_at_pattern(
    text: str,
    at_style: str = ThemeKey.USER_INPUT_AT_PATTERN,
    other_style: str = ThemeKey.USER_INPUT,
) -> Text:
    if "@" not in text:
        return Text(text, style=other_style)

    result = Text("")
    last_end = 0
    for match in AT_FILE_RENDER_PATTERN.finditer(text):
        start, end = match.span()
        if start > last_end:
            # Text before the @-pattern
            result.append_text(Text(text[last_end:start], other_style))
        # The @-pattern itself (e.g. @path or @"path with spaces")
        result.append_text(Text(text[start:end], at_style))
        last_end = end

    if last_end < len(text):
        result.append_text(Text(text[last_end:], other_style))

    return result


def render_user_input(content: str) -> RenderableType:
    """Render a user message as a group of quoted lines with styles.

    - Highlights slash command on the first line if recognized
    - Highlights @file patterns in all lines
    """
    lines = content.strip().split("\n")
    renderables: list[RenderableType] = []
    has_command = False
    for i, line in enumerate(lines):
        line_text = render_at_pattern(line)

        if i == 0 and line.startswith("/"):
            splits = line.split(" ", maxsplit=1)
            if is_slash_command_name(splits[0][1:]):
                has_command = True
                line_text = Text.assemble(
                    (f"{splits[0]}", ThemeKey.USER_INPUT_SLASH_COMMAND),
                    " ",
                    render_at_pattern(splits[1]) if len(splits) > 1 else Text(""),
                )
                renderables.append(line_text)
                continue

        renderables.append(line_text)
    grid = create_grid()
    grid.padding = (0, 0)
    mark = (
        Text("❯ ", style=ThemeKey.USER_INPUT_PROMPT)
        if not has_command
        else Text("  ", style=ThemeKey.USER_INPUT_SLASH_COMMAND)
    )
    grid.add_row(mark, Group(*renderables))
    return grid


def render_interrupt() -> RenderableType:
    return Text(" INTERRUPTED \n", style=ThemeKey.INTERRUPT)
