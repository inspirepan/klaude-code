# pyright: reportPrivateUsage=false
from __future__ import annotations

from klaude_code.tui.terminal.selector import SelectOverlay


def test_select_overlay_scroll_offsets_are_compact() -> None:
    overlay = SelectOverlay[str](use_search_filter=False)
    assert overlay._list_window is not None
    assert overlay._list_window.scroll_offsets.top == 1
    assert overlay._list_window.scroll_offsets.bottom == 0
    assert overlay._list_window.allow_scroll_beyond_bottom() is False
