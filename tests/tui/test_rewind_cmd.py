from klaude_code.tui.command.fork_session_cmd import ForkPoint, _style_fork_item
from klaude_code.tui.command.rewind_cmd import _build_rewind_select_items
from klaude_code.tui.terminal.selector import SelectItem, _build_choices_tokens


def _style_for(tokens: list[tuple[str, str]], text: str) -> str:
    expected = text.rstrip("\n")
    return next(style for style, token_text in tokens if token_text and token_text.rstrip("\n") == expected)


def _fork_points() -> list[ForkPoint]:
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


def test_rewind_picker_highlights_boundary_and_dims_summarized_content() -> None:
    tokens = _build_choices_tokens(_items(), [0, 1, 2, 3], 1, "→", item_style_transform=_style_fork_item)

    # The divider right above the pointed row marks the selected boundary;
    # the other from-here dividers stay plain.
    items = _items()
    assert "class:fork.selected-separator" in _separator_style(items[1], 1, 1)
    assert "class:fork.selected-separator" not in _separator_style(items[2], 2, 1)
    assert "class:fork.excluded" not in _style_for(tokens, "user:   before\n")

    # Everything from the pivot onward is summarized, not kept verbatim.
    for text in (
        "user:   selected\n",
        "user:   after\n",
    ):
        assert "class:fork.excluded" in _style_for(tokens, text)


def test_rewind_picker_updates_dimmed_range_when_pointer_moves() -> None:
    tokens = _build_choices_tokens(_items(), [0, 1, 2, 3], 2, "→", item_style_transform=_style_fork_item)

    assert "class:fork.excluded" not in _style_for(tokens, "user:   selected\n")
    assert "class:fork.excluded" in _style_for(tokens, "user:   after\n")
    # The boundary divider above the pointed row turns green; the end
    # divider does not.
    assert "class:fork.selected-separator" in _separator_style(_items()[2], 2, 2)
    assert "class:fork.selected-separator" not in _separator_style(_items()[3], 3, 2)


def test_rewind_picker_end_point_is_selectable_and_labeled() -> None:
    items = _items()

    end_item = items[-1]
    assert end_item.value == -1
    assert end_item.selectable is True
    # Every rewind point is selectable, including the very first user message.
    assert all(item.selectable for item in items)
