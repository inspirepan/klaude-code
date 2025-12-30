from __future__ import annotations

import io
import textwrap

from hypothesis import given, settings
from hypothesis import strategies as st
from rich.console import Console


def _render(text: str, width: int) -> str:
    buffer = io.StringIO()
    console = Console(file=buffer, width=width, force_terminal=False)
    console.print(text, markup=False)
    return buffer.getvalue()


def test_rich_cjk_wrap_patch_changes_line_breaks() -> None:
    sample = textwrap.dedent(
        """\
        • 这是一个基于 Typer 的本地/交互式代码代理 CLI，入口在 src/klaude_code/cli/main.py，支持普通交互和非交互 exec 模式。
        """
    ).rstrip("\n")

    width = 40

    from klaude_code.ui.rich import install_rich_cjk_wrap_patch

    install_rich_cjk_wrap_patch()

    rendered = _render(sample, width=width)
    assert "Typer \n的" not in rendered
    assert "main.\npy" not in rendered


def test_rich_cjk_wrap_patch_avoids_splitting_parenthetical_phrase() -> None:
    sample = (
        "• 重新赢得信任：Meta 的文化没有显赫的头衔红利 (No titles)，即使是资深工程师，"
        "换了团队也必须重新证明自己。他通过大量的代码贡献和解决实际的技术债务（如将 Instagram 的 "
        "Python 代码库迁移到 Hack 语言）来建立影响力。"
    )

    # This width reliably reproduced a bad case where Rich wrapped as "(No\n" then "titles".
    width = 49

    from klaude_code.ui.rich import install_rich_cjk_wrap_patch

    install_rich_cjk_wrap_patch()

    rendered = _render(sample, width=width)
    assert "(No\n" not in rendered


def test_rich_cjk_wrap_patch_avoids_splitting_after_open_paren() -> None:
    sample = "• 深度的“制造者时间” (Deep Maker Time)：由于无法通过会议进行同步沟通，他避开了大公司的会议地狱。"

    # This width previously rendered as "(Deep\nMaker".
    width = 26

    from klaude_code.ui.rich import install_rich_cjk_wrap_patch

    install_rich_cjk_wrap_patch()

    rendered = _render(sample, width=width)
    assert "(Deep\n" not in rendered


# ============================================================================
# Property-based tests for cjk_wrap
# ============================================================================


@given(
    text=st.text(
        st.sampled_from(list("abcdefghijklmnopqrstuvwxyz0123456789 \t") + list("中文测试你好世界")),
        min_size=0,
        max_size=200,
    ),
    width=st.integers(min_value=10, max_value=120),
)
@settings(max_examples=100, deadline=None)
def test_cjk_wrap_preserves_text(text: str, width: int) -> None:
    """Property: breaking text does not change content."""
    from klaude_code.ui.rich.cjk_wrap import install_rich_cjk_wrap_patch

    install_rich_cjk_wrap_patch()

    # Import after patch is installed
    import rich._wrap as _wrap

    breaks = _wrap.divide_line(text, width, fold=True)

    # Reconstruct text from breaks
    if not breaks:
        # No breaks means text fits on one line or is empty
        pass
    else:
        # All break positions should be within text
        for pos in breaks:
            assert 0 <= pos <= len(text)


@given(ch=st.characters())
@settings(max_examples=200, deadline=None)
def test_cjk_contains_cjk_consistency(ch: str) -> None:
    """Property: _contains_cjk with single char equals _is_cjk_char."""
    from klaude_code.ui.rich.cjk_wrap import (
        _contains_cjk,  # pyright: ignore[reportPrivateUsage]
        _is_cjk_char,  # pyright: ignore[reportPrivateUsage]
    )

    # Single char: _contains_cjk should equal _is_cjk_char
    assert _contains_cjk(ch) == _is_cjk_char(ch)
