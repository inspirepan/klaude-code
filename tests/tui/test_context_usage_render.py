from __future__ import annotations

from collections import Counter
from typing import cast

from rich.console import Console

from klaude_code.protocol import events
from klaude_code.protocol.models import ContextCategory, ContextCategoryKey, ContextUsageUIExtra
from klaude_code.tui.components.context_usage import (
    _allocate_cells,  # pyright: ignore[reportPrivateUsage]
    render_context_usage,
)
from klaude_code.tui.components.rich.theme import get_theme

_GRID_CELLS = 200


def _usage(context_limit: int, *, is_calibrated: bool = True, **categories: int) -> ContextUsageUIExtra:
    entries = [
        ContextCategory(key=cast(ContextCategoryKey, key), label=key, tokens=tokens)
        for key, tokens in categories.items()
    ]
    used = sum(tokens for key, tokens in categories.items() if key != "free")
    return ContextUsageUIExtra(
        model_name="Test Model",
        model_id="test-model",
        used_tokens=used,
        context_limit=context_limit,
        categories=entries,
        is_calibrated=is_calibrated,
    )


def test_empty_context_fills_no_cells() -> None:
    assert _allocate_cells(_usage(1_000_000)) == []


def test_cells_track_the_occupied_share_of_the_window() -> None:
    # 10% of the window occupied should light up 10% of the grid.
    cells = _allocate_cells(_usage(200_000, messages=20_000))

    assert len(cells) == _GRID_CELLS // 10


def test_full_context_fills_every_cell() -> None:
    assert len(_allocate_cells(_usage(200_000, messages=200_000))) == _GRID_CELLS


def test_usage_beyond_the_limit_is_clamped_to_the_grid() -> None:
    assert len(_allocate_cells(_usage(100_000, messages=150_000))) == _GRID_CELLS


def test_unknown_limit_fills_the_grid_to_show_relative_shares() -> None:
    cells = _allocate_cells(_usage(0, system_prompt=1_000, messages=3_000))

    assert len(cells) == _GRID_CELLS
    counts = Counter(cells)
    assert counts["messages"] == 3 * counts["system_prompt"]


def test_free_space_never_occupies_cells() -> None:
    cells = _allocate_cells(_usage(200_000, messages=20_000, free=180_000))

    assert "free" not in set(cells)
    assert len(cells) == _GRID_CELLS // 10


def test_cells_are_split_between_categories_in_proportion() -> None:
    cells = _allocate_cells(_usage(200_000, system_prompt=20_000, messages=60_000))

    counts = Counter(cells)
    assert counts["messages"] == 3 * counts["system_prompt"]


def test_render_lists_every_category_and_the_model() -> None:
    usage = _usage(
        200_000,
        system_prompt=5_000,
        system_tools=10_000,
        messages=3_000,
        free=182_000,
    )
    console = Console(theme=get_theme(None).app_theme, width=120, no_color=True)

    with console.capture() as capture:
        console.print(render_context_usage(events.ContextUsageEvent(session_id="s", usage=usage)))
    output = capture.get()

    assert "Context Usage" in output
    assert "Test Model" in output
    assert "test-model" in output
    assert "18k/200k tokens (9.0%)" in output
    for label in ("system_prompt", "system_tools", "messages", "free"):
        assert label in output


def test_uncalibrated_render_says_the_numbers_are_estimates() -> None:
    usage = _usage(200_000, messages=3_000, is_calibrated=False)
    console = Console(theme=get_theme(None).app_theme, width=120, no_color=True)

    with console.capture() as capture:
        console.print(render_context_usage(events.ContextUsageEvent(session_id="s", usage=usage)))
    output = capture.get()

    assert "Estimated usage by category" in output
    assert "Estimated locally" in output


def test_calibrated_render_drops_the_estimate_caveat() -> None:
    usage = _usage(200_000, messages=3_000, is_calibrated=True)
    console = Console(theme=get_theme(None).app_theme, width=120, no_color=True)

    with console.capture() as capture:
        console.print(render_context_usage(events.ContextUsageEvent(session_id="s", usage=usage)))
    output = capture.get()

    assert "Usage by category" in output
    assert "Estimated locally" not in output
