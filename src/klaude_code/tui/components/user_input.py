import re

from rich.console import Group, RenderableType
from rich.padding import Padding
from rich.text import Text

from klaude_code.const import TAB_EXPAND_WIDTH
from klaude_code.skill import list_skill_names
from klaude_code.tui.components.bash_syntax import highlight_bash_command
from klaude_code.tui.components.rich.theme import ThemeKey

# Match inline patterns only when they appear at the beginning of the line
# or immediately after whitespace, to avoid treating mid-word email-like
# patterns such as foo@bar.com as file references.
# Group 1 is present only for $/¥ skills and captures the skill token (without the $/¥).
INLINE_RENDER_PATTERN = re.compile(r'(?<!\S)(?:@(?:"[^"]+"|\S+)|[$¥](\S+))')
USER_MESSAGE_MARK = "❯ "


def render_at_and_skill_patterns(
    text: str,
    at_style: str = ThemeKey.USER_INPUT_AT_PATTERN,
    skill_style: str = ThemeKey.USER_INPUT_SKILL,
    other_style: str = ThemeKey.USER_INPUT,
    available_skill_names: set[str] | None = None,
) -> Text:
    """Render text with highlighted @file and $skill patterns."""
    result = Text(text, style=other_style)
    for match in INLINE_RENDER_PATTERN.finditer(text):
        skill_name = match.group(1)
        if skill_name is None:
            result.stylize(at_style, match.start(), match.end())
            continue

        if available_skill_names is None:
            available_skill_names = set(list_skill_names())

        short = skill_name.split(":")[-1] if ":" in skill_name else skill_name
        if skill_name in available_skill_names or short in available_skill_names:
            result.stylize(skill_style, match.start(), match.end())

    return result


def render_user_input(content: str) -> RenderableType:
    """Render a user message as a group of quoted lines with styles.

    - Highlights slash command token on the first line
    - Highlights @file and $skill patterns in all lines
    - Wrapped in a Panel for block-style background
    """
    lines = content.strip().split("\n")
    is_bash_mode = bool(lines) and lines[0].startswith("!")

    available_skill_names: set[str] | None = None

    renderables: list[RenderableType] = []
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        if "\t" in line:
            line = line.expandtabs(TAB_EXPAND_WIDTH)

        if is_bash_mode and i == 0:
            renderables.append(highlight_bash_command(line[1:]))
            continue
        if is_bash_mode and i > 0:
            renderables.append(highlight_bash_command(line))
            continue

        if available_skill_names is None and ("$" in line or "\u00a5" in line):
            available_skill_names = set(list_skill_names())
        # Handle slash command on first line
        if i == 0 and line.startswith("/"):
            splits = line.split(" ", maxsplit=1)
            line_text = Text.assemble(
                (splits[0], ThemeKey.USER_INPUT_SLASH_COMMAND),
                " ",
                render_at_and_skill_patterns(splits[1], available_skill_names=available_skill_names)
                if len(splits) > 1
                else Text(""),
            )
            renderables.append(line_text)
            continue

        # Render @file and $skill patterns
        renderables.append(render_at_and_skill_patterns(line, available_skill_names=available_skill_names))

    return Padding(
        Group(*renderables),
        pad=(0, 1),
        style=ThemeKey.USER_INPUT,
        expand=False,
    )


def render_interrupt() -> RenderableType:
    return Text("Interrupted by user", style=ThemeKey.INTERRUPT)
