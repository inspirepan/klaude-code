from __future__ import annotations

from prompt_toolkit.formatted_text import StyleAndTextTuples

from klaude_code.tui.input.prompt_toolkit import _trim_formatted_text_with_ellipsis  # pyright: ignore[reportPrivateUsage]


def _render_fragments(text: StyleAndTextTuples) -> str:
    return "".join(fragment[1] for fragment in text)


def test_trim_formatted_text_uses_unicode_ellipsis() -> None:
    text, width = _trim_formatted_text_with_ellipsis([("", "abcdefgh")], 5)
    rendered = _render_fragments(text)

    assert rendered == "abcd…"
    assert width == 5


def test_trim_formatted_text_keeps_text_when_width_is_enough() -> None:
    text, width = _trim_formatted_text_with_ellipsis([("", "abc")], 5)
    rendered = _render_fragments(text)

    assert rendered == "abc"
    assert width == 3
