from rich.console import Console

from klaude_code.protocol import events, message, model
from klaude_code.tui.components.developer import render_developer_message
from klaude_code.tui.components.rich.theme import ThemeKey, get_theme


def test_render_developer_message_skill_name_uses_skill_style() -> None:
    console = Console(width=120, record=False, force_terminal=False, theme=get_theme().app_theme)
    event = events.DeveloperMessageEvent(
        session_id="test-session",
        item=message.DeveloperMessage(
            parts=[],
            ui_extra=model.DeveloperUIExtra(items=[model.SkillActivatedUIItem(name="commit")]),
        ),
    )

    line = console.render_lines(render_developer_message(event), console.options, pad=False)[0]
    parts: list[tuple[str, object]] = [(segment.text, segment.style) for segment in line]
    full_text = "".join(text for text, _ in parts)
    skill_name_start = full_text.index("commit")

    def style_at(index: int) -> object:
        offset = 0
        for text, style in parts:
            end = offset + len(text)
            if offset <= index < end:
                return style
            offset = end
        raise AssertionError(f"No style found at index {index}")

    assert style_at(skill_name_start) == console.get_style(ThemeKey.TOOL_PARAM_FILE_PATH_SKILL_NAME)
