import json

from rich.console import Console

from klaude_code.tui.components.rich.theme import ThemeKey, get_theme
from klaude_code.tui.components.tools import render_read_tool_call


def _render_to_text(arguments: str) -> str:
    console = Console(width=120, record=True, force_terminal=False, theme=get_theme().app_theme)
    console.print(render_read_tool_call(arguments))
    return console.export_text()


def test_render_read_tool_call_with_numeric_range() -> None:
    output = _render_to_text(
        json.dumps(
            {
                "file_path": "/tmp/a.txt",
                "offset": 10,
                "limit": 5,
            }
        )
    )

    assert "10:14" in output


def test_render_read_tool_call_with_list_offset_does_not_crash() -> None:
    output = _render_to_text(
        json.dumps(
            {
                "file_path": "/tmp/a.txt",
                "offset": [335],
                "limit": 200,
            }
        )
    )

    assert "Read" in output
    assert "offset=[335]" in output


def test_render_read_skill_path_segment_styles() -> None:
    console = Console(width=120, record=False, force_terminal=False, theme=get_theme().app_theme)
    arguments = json.dumps({"file_path": "/Users/x/.claude/skills/commit/SKILL.md"})
    line = console.render_lines(render_read_tool_call(arguments), console.options, pad=False)[0]

    parts: list[tuple[str, object]] = [(segment.text, segment.style) for segment in line]
    full_text = "".join(text for text, _ in parts)
    suffix = "commit/SKILL.md"
    suffix_start = full_text.index(suffix)

    def style_at(index: int) -> object:
        offset = 0
        for text, style in parts:
            end = offset + len(text)
            if offset <= index < end:
                return style
            offset = end
        raise AssertionError(f"No style found at index {index}")

    skill_name_style = console.get_style(ThemeKey.TOOL_PARAM_FILE_PATH_SKILL_NAME)
    slash_style = console.get_style(ThemeKey.TOOL_PARAM)
    skill_file_style = console.get_style(ThemeKey.TOOL_PARAM_FILE_PATH_SKILL_FILE)

    assert style_at(suffix_start) == skill_name_style
    assert style_at(suffix_start + len("commit")) == slash_style
    assert style_at(suffix_start + len("commit/")) == skill_file_style


def test_render_read_tool_call_long_path_folds_without_ellipsis() -> None:
    console = Console(width=40, record=True, force_terminal=False, theme=get_theme().app_theme)
    arguments = json.dumps(
        {
            "file_path": "/tmp/very/long/path/for/read/tool/call/that/should/fold/instead/of/truncate/output.txt",
            "offset": 1,
            "limit": 400,
        }
    )

    console.print(render_read_tool_call(arguments))
    output = console.export_text()

    assert "…" not in output
    assert "output.txt" in output
    assert "1:400" in output
