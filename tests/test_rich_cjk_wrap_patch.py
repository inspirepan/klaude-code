from __future__ import annotations

import io
import textwrap

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

    before = _render(sample, width=width)
    assert "Typer \n的" in before

    # Install patch (module import also installs eagerly).
    from klaude_code.ui.rich import install_rich_cjk_wrap_patch

    install_rich_cjk_wrap_patch()

    after = _render(sample, width=width)
    assert "Typer \n的" not in after
    assert "main.\npy" not in after
