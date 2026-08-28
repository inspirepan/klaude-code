from klaude_code.tui.command.fork_session_cmd import ForkPoint, _style_fork_item
from klaude_code.tui.command.rewind_cmd import _build_rewind_select_items
from klaude_code.tui.terminal.selector import SelectItem, _build_choices_tokens


def _style_for(tokens: list[tuple[str, str]], text: str) -> str:
    expected = text.rstrip("\n")
    return next(style for style, token_text in tokens if token_text and token_text.rstrip("\n") == expected)


def _fork_points() -> list[ForkPoint]:
    # _build_fork_points order: chronological user points, "end" appended last.
    return [
        ForkPoint(kind="user", history_index=0, tool_call_stats={}, user_message="before"),
        ForkPoint(kind="user", history_index=2, tool_call_stats={}, user_message="selected"),
        ForkPoint(kind="user", history_index=4, tool_call_stats={}, user_message="after"),
        ForkPoint(kind="end", history_index=-1, tool_call_stats={}),
    ]


def _items() -> list[SelectItem[int]]:
    return _build_rewind_select_items(_fork_points())


def _separator_style(item: SelectItem[int], item_index: int, pointed_index: int) -> str:
    styled = _style_fork_item(item.title, item_index, pointed_index)
    return next(style for style, text in styled if "class:separator" in style.split())


def test_rewind_picker_puts_entire_conversation_on_top() -> None:
    items = _items()

    assert items[0].value == -1
    assert items[0].selectable is True
    assert items[0].title[0] == (
        "class:separator",
        "----- rewind entire conversation (summarize everything) -----\n\n",
    )
    # Chronological user points follow, each with a from-here divider above
    # except the topmost user boundary.
    assert [item.value for item in items[1:]] == [0, 2, 4]
    assert "class:separator" not in {style for style, _ in items[1].title}


def test_rewind_picker_highlights_boundary_and_dims_summarized_content() -> None:
    # Pointing at the second user point: everything from it onward greys out —
    # including the pointed row itself (the pivot is summarized, not kept).
    tokens = _build_choices_tokens(_items(), [0, 1, 2, 3], 2, "→", item_style_transform=_style_fork_item)

    assert "class:fork.selected-separator" in _separator_style(_items()[2], 2, 2)
    assert "class:fork.excluded" not in _style_for(tokens, "user:   before\n")
    assert "class:fork.excluded" in _style_for(tokens, "user:   selected\n")
    assert "class:fork.excluded" in _style_for(tokens, "user:   after\n")


def test_rewind_picker_pointing_at_entire_conversation_dims_everything() -> None:
    tokens = _build_choices_tokens(_items(), [0, 1, 2, 3], 0, "→", item_style_transform=_style_fork_item)

    assert "class:fork.selected-separator" in _separator_style(_items()[0], 0, 0)
    for text in ("user:   before\n", "user:   selected\n", "user:   after\n"):
        assert "class:fork.excluded" in _style_for(tokens, text)


def test_rewind_picker_updates_dimmed_range_when_pointer_moves() -> None:
    tokens = _build_choices_tokens(_items(), [0, 1, 2, 3], 3, "→", item_style_transform=_style_fork_item)

    assert "class:fork.excluded" not in _style_for(tokens, "user:   selected\n")
    assert "class:fork.excluded" in _style_for(tokens, "user:   after\n")
    # The boundary divider above the pointed row turns green; the top
    # divider does not.
    assert "class:fork.selected-separator" in _separator_style(_items()[3], 3, 3)
    assert "class:fork.selected-separator" not in _separator_style(_items()[0], 0, 3)


def test_rewind_picker_selectability() -> None:
    items = _items()

    # "Rewind entire conversation" is selectable...
    assert items[0].value == -1
    assert items[0].selectable is True
    # ...and covers the whole conversation, so the first user point (an exact
    # duplicate of it) stays non-selectable, matching /fork's convention.
    assert items[1].selectable is False
    assert [item.selectable for item in items[2:]] == [True, True]
