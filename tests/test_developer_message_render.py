from rich.console import Console

from klaude_code.protocol import events, message
from klaude_code.protocol.models import (
    DeveloperUIExtra,
    SkillActivatedUIItem,
    SkillDiscoveredUIItem,
    SkillListingUIItem,
)
from klaude_code.tui.components.developer import render_developer_message
from klaude_code.tui.components.rich.theme import ThemeKey, get_theme


def test_render_developer_message_skill_name_uses_skill_style() -> None:
    console = Console(width=120, record=False, force_terminal=False, theme=get_theme().app_theme)
    event = events.DeveloperMessageEvent(
        session_id="test-session",
        item=message.DeveloperMessage(
            parts=[],
            ui_extra=DeveloperUIExtra(items=[SkillActivatedUIItem(name="commit")]),
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


def test_render_developer_message_discovered_skills_are_grouped_without_skill_style() -> None:
    console = Console(width=120, record=False, force_terminal=False, theme=get_theme().app_theme)
    event = events.DeveloperMessageEvent(
        session_id="test-session",
        item=message.DeveloperMessage(
            parts=[],
            ui_extra=DeveloperUIExtra(
                items=[
                    SkillDiscoveredUIItem(name="commit"),
                    SkillDiscoveredUIItem(name="submit-pr"),
                ]
            ),
        ),
    )

    line = console.render_lines(render_developer_message(event), console.options, pad=False)[0]
    parts: list[tuple[str, object]] = [(segment.text, segment.style) for segment in line]
    full_text = "".join(text for text, _ in parts)
    assert full_text == "+ Discovered skills commit, submit-pr"
    skill_name_start = full_text.index("commit")
    second_skill_start = full_text.index("submit-pr")

    def style_at(index: int) -> object:
        offset = 0
        for text, style in parts:
            end = offset + len(text)
            if offset <= index < end:
                return style
            offset = end
        raise AssertionError(f"No style found at index {index}")

    assert style_at(skill_name_start) == console.get_style(ThemeKey.ATTACHMENT)
    assert style_at(second_skill_start) == console.get_style(ThemeKey.ATTACHMENT)


def test_render_developer_message_available_skills_use_skill_style() -> None:
    console = Console(width=120, record=False, force_terminal=False, theme=get_theme().app_theme)
    event = events.DeveloperMessageEvent(
        session_id="test-session",
        item=message.DeveloperMessage(
            parts=[],
            ui_extra=DeveloperUIExtra(items=[SkillListingUIItem(names=["commit", "submit-pr"])]),
        ),
    )

    line = console.render_lines(render_developer_message(event), console.options, pad=False)[0]
    parts: list[tuple[str, object]] = [(segment.text, segment.style) for segment in line]
    full_text = "".join(text for text, _ in parts)
    assert full_text == "+ 2 available skills"
    assert all(style == console.get_style(ThemeKey.ATTACHMENT) for _, style in parts if _.strip())


def test_render_developer_message_incremental_available_skills_lists_names() -> None:
    console = Console(width=120, record=False, force_terminal=False, theme=get_theme().app_theme)
    event = events.DeveloperMessageEvent(
        session_id="test-session",
        item=message.DeveloperMessage(
            parts=[],
            ui_extra=DeveloperUIExtra(items=[SkillListingUIItem(names=["commit", "submit-pr"], incremental=True)]),
        ),
    )

    line = console.render_lines(render_developer_message(event), console.options, pad=False)[0]
    parts: list[tuple[str, object]] = [(segment.text, segment.style) for segment in line]
    full_text = "".join(text for text, _ in parts)
    assert full_text == "+ Updated available skills commit, submit-pr"
    assert all(style == console.get_style(ThemeKey.ATTACHMENT) for _, style in parts if _.strip())
