"""`/btw` panel rendering: question, answer, and the forked request's cache hit."""

from __future__ import annotations

from rich.console import Console

from klaude_code.protocol import events
from klaude_code.tui.components.rich.theme import get_theme
from klaude_code.tui.components.side_question import render_side_question


def _render(cache_hit_rate: float | None) -> str:
    themes = get_theme("dark")
    console = Console(theme=themes.app_theme, width=60, no_color=True, legacy_windows=False)
    console.push_theme(themes.markdown_theme)
    event = events.SideQuestionEvent(
        session_id="s1",
        question="why is this cached?",
        answer="Because the prefix matches.",
        cache_hit_rate=cache_hit_rate,
    )
    with console.capture() as capture:
        console.print(render_side_question(event, code_theme=themes.code_theme, width=58))
    return capture.get()


def test_panel_shows_question_answer_and_cache_hit_rate() -> None:
    output = _render(0.976)

    assert "btw" in output
    assert "why is this cached?" in output
    assert "Because the prefix matches." in output
    # The rate closes the panel's last line.
    assert "cache hit 98%" in output.splitlines()[-1]


def test_panel_omits_the_cache_footer_when_usage_is_unknown() -> None:
    output = _render(None)

    assert "cache hit" not in output
