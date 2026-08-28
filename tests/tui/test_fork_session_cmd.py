from klaude_code.tui.command.fork_session_cmd import _style_fork_item
from klaude_code.tui.terminal.selector import SelectItem, _build_choices_tokens


def _style_for(tokens: list[tuple[str, str]], text: str) -> str:
    expected = text.rstrip("\n")
    return next(style for style, token_text in tokens if token_text and token_text.rstrip("\n") == expected)


def _items() -> list[SelectItem[int]]:
    return [
        SelectItem(
            title=[("class:msg", "user: before\n")],
            value=0,
            search_text="before",
        ),
        SelectItem(
            title=[
                ("class:separator", "----- fork from here -----\n"),
                ("class:msg", "user: selected\n"),
                ("class:meta", "tools: selected\n"),
                ("class:assistant", "ai: selected\n"),
            ],
            value=1,
            search_text="selected",
        ),
        SelectItem(
            title=[
                ("class:separator", "----- later fork -----\n"),
                ("class:msg", "user: after\n"),
                ("class:meta", "tools: after\n"),
                ("class:assistant", "ai: after\n"),
            ],
            value=2,
            search_text="after",
        ),
    ]


def test_fork_picker_highlights_boundary_and_dims_excluded_content() -> None:
    tokens = _build_choices_tokens(
        _items(),
        [0, 1, 2],
        1,
        "→",
        item_style_transform=_style_fork_item,
    )

    assert "class:fork.excluded" not in _style_for(tokens, "user: before\n")
    assert "class:fork.selected-separator" in _style_for(tokens, "----- fork from here -----\n")
    assert "class:fork.selected-separator" not in _style_for(tokens, "----- later fork -----\n")

    for text in (
        "user: selected\n",
        "tools: selected\n",
        "ai: selected\n",
        "user: after\n",
        "tools: after\n",
        "ai: after\n",
    ):
        assert "class:fork.excluded" in _style_for(tokens, text)


def test_fork_picker_updates_dimmed_range_when_pointer_moves() -> None:
    tokens = _build_choices_tokens(
        _items(),
        [0, 1, 2],
        2,
        "→",
        item_style_transform=_style_fork_item,
    )

    assert "class:fork.excluded" not in _style_for(tokens, "user: selected\n")
    assert "class:fork.excluded" in _style_for(tokens, "user: after\n")
    assert "class:fork.selected-separator" in _style_for(tokens, "----- later fork -----\n")
