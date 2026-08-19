# pyright: reportPrivateUsage=false
from __future__ import annotations

from collections.abc import Callable
from types import SimpleNamespace
from typing import cast
from unittest.mock import patch

from klaude_code.tui.terminal.selector import SelectItem, SelectOverlay, _overlay_list_cap


def _build_overlay(
    *,
    list_height: int = 20,
    get_reserved_rows: Callable[[], int] | None = None,
) -> SelectOverlay[str]:
    overlay = SelectOverlay[str](list_height=list_height, get_reserved_rows=get_reserved_rows)
    items = [SelectItem(title=[("class:msg", f"item {i}\n")], value=str(i), search_text=f"item {i}") for i in range(30)]
    overlay.set_content(message="Select a model:", items=items)
    return overlay


def _list_height(overlay: SelectOverlay[str], *, rows: int, columns: int = 80) -> int:
    assert overlay._list_window is not None
    assert callable(overlay._list_window.height)
    height = cast("Callable[[], int]", overlay._list_window.height)
    app = SimpleNamespace(output=SimpleNamespace(get_size=lambda: SimpleNamespace(rows=rows, columns=columns)))
    with patch("klaude_code.tui.terminal.selector.get_app", return_value=app):
        return height()


def test_overlay_list_uses_configured_height_on_tall_terminal() -> None:
    overlay = _build_overlay(list_height=20)

    assert _list_height(overlay, rows=40) == 20


def test_overlay_list_shrinks_on_short_terminal() -> None:
    overlay = _build_overlay(list_height=20)

    # Overlay chrome (frame 2 + header 1 + search 1) plus the fallback host
    # rows (3) leaves 15 - 7 = 8 rows for the list.
    assert _list_height(overlay, rows=15) == 8


def test_overlay_list_floors_at_one_row_on_tiny_terminal() -> None:
    overlay = _build_overlay(list_height=20)

    # A fixed lower bound here would push the enclosing HSplit past the
    # screen height and prompt_toolkit would render "Window too small...".
    assert _list_height(overlay, rows=6) == 1


def test_overlay_list_subtracts_host_reserved_rows() -> None:
    overlay = _build_overlay(list_height=20, get_reserved_rows=lambda: 10)

    # 20 rows - chrome 4 - host 10 = 6 rows for the list.
    assert _list_height(overlay, rows=20) == 6


def test_overlay_list_cap_ignores_unknown_terminal_size() -> None:
    assert _overlay_list_cap(configured_height=20, terminal_rows=0, overhead_rows=7) == 20
    assert _overlay_list_cap(configured_height=20, terminal_rows=30, overhead_rows=7) == 20
    assert _overlay_list_cap(configured_height=20, terminal_rows=12, overhead_rows=7) == 5
    assert _overlay_list_cap(configured_height=20, terminal_rows=5, overhead_rows=7) == 1
