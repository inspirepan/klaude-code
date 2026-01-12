import re

from rich.console import Group, RenderableType
from rich.text import Text

from klaude_code.const import TAB_EXPAND_WIDTH
from klaude_code.skill import get_available_skills
from klaude_code.tui.components.bash_syntax import highlight_bash_command
from klaude_code.tui.components.rich.theme import ThemeKey

# Match @-file patterns only when they appear at the beginning of the line
# or immediately after whitespace, to avoid treating mid-word email-like
# patterns such as foo@bar.com as file references.
AT_FILE_RENDER_PATTERN = re.compile(r'(?<!\S)@("([^"]+)"|\S+)')

# Match $skill or ¥skill pattern inline (at start of line or after whitespace)
SKILL_RENDER_PATTERN = re.compile(r"(?<!\S)[$¥](\S+)")

USER_MESSAGE_MARK = "❯ "


def render_at_and_skill_patterns(
    text: str,
    at_style: str = ThemeKey.USER_INPUT_AT_PATTERN,
    skill_style: str = ThemeKey.USER_INPUT_SKILL,
    other_style: str = ThemeKey.USER_INPUT,
) -> Text:
    """Render text with highlighted @file and $skill patterns."""
    has_at = "@" in text
    has_skill = "$" in text or "\u00a5" in text  # $ or ¥

    if not has_at and not has_skill:
        return Text(text, style=other_style)

    # Collect all matches with their styles
    matches: list[tuple[int, int, str]] = []  # (start, end, style)

    if has_at:
        for match in AT_FILE_RENDER_PATTERN.finditer(text):
            matches.append((match.start(), match.end(), at_style))

    if has_skill:
        for match in SKILL_RENDER_PATTERN.finditer(text):
            skill_name = match.group(1)
            if _is_valid_skill_name(skill_name):
                matches.append((match.start(), match.end(), skill_style))

    if not matches:
        return Text(text, style=other_style)

    # Sort by start position
    matches.sort(key=lambda x: x[0])

    result = Text("")
    last_end = 0
    for start, end, style in matches:
        if start < last_end:
            continue  # Skip overlapping matches
        if start > last_end:
            result.append_text(Text(text[last_end:start], other_style))
        result.append_text(Text(text[start:end], style))
        last_end = end

    if last_end < len(text):
        result.append_text(Text(text[last_end:], other_style))

    return result


def _is_valid_skill_name(name: str) -> bool:
    """Check if a skill name is valid (exists in loaded skills)."""
    short = name.split(":")[-1] if ":" in name else name
    available_skills = get_available_skills()
    return any(skill_name in (name, short) for skill_name, _, _ in available_skills)


def render_user_input(content: str) -> RenderableType:
    """Render a user message as a group of quoted lines with styles.

    - Highlights slash command token on the first line
    - Highlights @file and $skill patterns in all lines
    """
    lines = content.strip().split("\n")
    is_bash_mode = bool(lines) and lines[0].startswith("!")
    renderables: list[RenderableType] = []
    for i, line in enumerate(lines):
        line = line.expandtabs(TAB_EXPAND_WIDTH)

        if is_bash_mode and i == 0:
            renderables.append(highlight_bash_command(line[1:]))
            continue
        if is_bash_mode and i > 0:
            renderables.append(highlight_bash_command(line))
            continue
        # Handle slash command on first line
        if i == 0 and line.startswith("/"):
            splits = line.split(" ", maxsplit=1)
            line_text = Text.assemble(
                (splits[0], ThemeKey.USER_INPUT_SLASH_COMMAND),
                " ",
                render_at_and_skill_patterns(splits[1]) if len(splits) > 1 else Text(""),
            )
            renderables.append(line_text)
            continue

        # Render @file and $skill patterns
        renderables.append(render_at_and_skill_patterns(line))

    return Group(*renderables)


def render_interrupt() -> RenderableType:
    return Text("Interrupted by user", style=ThemeKey.INTERRUPT)
