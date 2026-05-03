from rich.console import Group, RenderableType
from rich.text import Text

from klaude_code.const import TAB_EXPAND_WIDTH
from klaude_code.protocol.input_syntax import INLINE_RENDER_PATTERN
from klaude_code.skill import list_skill_names
from klaude_code.tui.command import is_slash_command_name
from klaude_code.tui.components.bash_syntax import highlight_bash_command
from klaude_code.tui.components.rich.quote import TreeQuote
from klaude_code.tui.components.rich.theme import ThemeKey

USER_MESSAGE_MARK = "❯ "


def render_bash_input_line(text: str) -> Text:
    """Render a bash input line with syntax colors on top of the user message background."""
    highlighted = highlight_bash_command(text)
    highlighted.style = ThemeKey.USER_INPUT
    return highlighted


def render_at_and_skill_patterns(
    text: str,
    at_style: str = ThemeKey.USER_INPUT_AT_PATTERN,
    skill_style: str = ThemeKey.USER_INPUT_SKILL,
    other_style: str = ThemeKey.USER_INPUT,
    available_skill_names: set[str] | None = None,
) -> Text:
    """Render text with highlighted @file and skill patterns."""
    result = Text(text, style=other_style, overflow="fold")
    for match in INLINE_RENDER_PATTERN.finditer(text):
        token_start = match.start("token")
        token_end = match.end("token")
        skill_token = match.group("skill_token")
        if skill_token is None:
            result.stylize(at_style, token_start, token_end)
            continue

        skill_name = skill_token.removeprefix("//skill:").removeprefix("/skill:")

        if available_skill_names is None:
            available_skill_names = set(list_skill_names())

        short = skill_name.split(":")[-1] if ":" in skill_name else skill_name
        if skill_name in available_skill_names or short in available_skill_names:
            result.stylize(skill_style, token_start, token_end)

    return result


def build_user_input_lines(content: str) -> list[Text]:
    """Build rendered lines for user input."""

    lines = content.strip().split("\n")
    is_bash_mode = bool(lines) and lines[0].startswith("!")

    available_skill_names: set[str] | None = None

    renderables: list[Text] = []
    for i, line in enumerate(lines):
        if "\t" in line:
            line = line.expandtabs(TAB_EXPAND_WIDTH)

        if is_bash_mode and i == 0:
            renderables.append(render_bash_input_line(line[1:]))
            continue
        if is_bash_mode and i > 0:
            renderables.append(render_bash_input_line(line))
            continue

        if available_skill_names is None and "/" in line:
            available_skill_names = set(list_skill_names())
        # Handle slash command on first line
        if i == 0 and line.startswith("/"):
            splits = line.split(" ", maxsplit=1)
            token = splits[0]
            if token.startswith("/") and not token.startswith("//") and is_slash_command_name(token[1:]):
                line_text = Text.assemble(
                    (token, ThemeKey.USER_INPUT_SLASH_COMMAND),
                    " ",
                    render_at_and_skill_patterns(
                        splits[1],
                        available_skill_names=available_skill_names,
                    )
                    if len(splits) > 1
                    else Text(""),
                    overflow="fold",
                )
                renderables.append(line_text)
                continue

        # Render @file and skill patterns
        renderables.append(
            render_at_and_skill_patterns(
                line,
                available_skill_names=available_skill_names,
            )
        )

    return renderables


def render_user_input(content: str) -> RenderableType:
    """Render a user message with a prompt on the first line.

    - Highlights slash command token on the first line
    - Highlights @file and /skill patterns in all lines
    """
    renderables = build_user_input_lines(content)

    if not renderables:
        return Text("", style=ThemeKey.USER_INPUT)

    return TreeQuote(
        Group(*renderables),
        prefix_first=USER_MESSAGE_MARK,
        prefix_middle=" " * len(USER_MESSAGE_MARK),
        prefix_last=" " * len(USER_MESSAGE_MARK),
        style=ThemeKey.USER_INPUT,
        style_first=ThemeKey.USER_INPUT,
    )


def render_interrupt() -> RenderableType:
    return Text("Interrupted by user", style=ThemeKey.INTERRUPT)
