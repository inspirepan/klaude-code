import json

from rich.console import Console

from klaude_code.tui.components.rich.theme import get_theme
from klaude_code.tui.components.tools import render_look_at_tool_call


def _render_to_text(arguments: str, width: int = 120) -> str:
    console = Console(width=width, record=True, force_terminal=False, theme=get_theme().app_theme)
    console.print(render_look_at_tool_call(arguments))
    return console.export_text()


def test_render_look_at_shows_path_and_question() -> None:
    output = _render_to_text(
        json.dumps(
            {
                "file_path": "/tmp/imgs/summary.png",
                "question": "请完整描述这张图片的内容",
            },
            ensure_ascii=False,
        )
    )

    assert "Look At" in output
    assert "/tmp/imgs/summary.png" in output
    assert "请完整描述这张图片的内容" in output
    # Raw key names from the generic renderer must not appear
    assert "file_path:" not in output
    assert "question:" not in output


def test_render_look_at_shows_region_annotation() -> None:
    output = _render_to_text(json.dumps({"file_path": "/tmp/a.png", "question": "zoom", "region": [10, 20, 300, 200]}))

    assert "[10,20 → 300,200]" in output


def test_render_look_at_long_question_is_truncated() -> None:
    output = _render_to_text(
        json.dumps({"file_path": "/tmp/a.png", "question": "词" * 200}, ensure_ascii=False),
        width=400,
    )

    assert "词" * 200 not in output
    assert "…" in output


def test_render_look_at_without_question_does_not_crash() -> None:
    output = _render_to_text(json.dumps({"file_path": "/tmp/a.png"}))

    assert "Look At" in output
    assert "/tmp/a.png" in output


def test_render_look_at_invalid_json_does_not_crash() -> None:
    output = _render_to_text("{not json")

    assert "Look At" in output
