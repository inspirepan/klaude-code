"""Tests for CJK-aware display width in markdown preview box."""

from __future__ import annotations

from klaude_code.tui.terminal.ask_user_question import (
    _display_width,  # pyright: ignore[reportPrivateUsage]
    _render_markdown_preview,  # pyright: ignore[reportPrivateUsage]
    _trim_to_display_width,  # pyright: ignore[reportPrivateUsage]
)


class TestDisplayWidth:
    def test_ascii_only(self) -> None:
        assert _display_width("hello") == 5

    def test_cjk_characters(self) -> None:
        # Each CJK character occupies 2 terminal columns
        assert _display_width("你好") == 4

    def test_mixed_ascii_cjk(self) -> None:
        assert _display_width("hi你好") == 6  # 2 + 4

    def test_empty_string(self) -> None:
        assert _display_width("") == 0


class TestTrimToDisplayWidth:
    def test_ascii_no_trim(self) -> None:
        assert _trim_to_display_width("hello", 10) == "hello"

    def test_ascii_trim(self) -> None:
        assert _trim_to_display_width("hello world", 5) == "hello"

    def test_cjk_trim_at_boundary(self) -> None:
        # "你好世界" = 8 columns, trim to 4 should keep "你好"
        assert _trim_to_display_width("你好世界", 4) == "你好"

    def test_cjk_trim_odd_width(self) -> None:
        # "你好" = 4 columns, trim to 3 should keep only "你" (2 cols)
        # because adding "好" (2 cols) would exceed 3
        assert _trim_to_display_width("你好", 3) == "你"

    def test_mixed_trim(self) -> None:
        # "a你b好" = 1+2+1+2 = 6 columns, trim to 4 should keep "a你b"
        assert _trim_to_display_width("a你b好", 4) == "a你b"

    def test_no_trim_needed(self) -> None:
        assert _trim_to_display_width("你好", 10) == "你好"

    def test_zero_width(self) -> None:
        assert _trim_to_display_width("abc", 0) == ""


class TestPreviewBoxAlignment:
    """Verify that preview box rows have consistent display width."""

    def _build_preview_row(self, line: str, inner_width: int) -> str:
        trimmed = _trim_to_display_width(line, inner_width)
        padding = " " * max(0, inner_width - _display_width(trimmed))
        return f"│ {trimmed}{padding} │"

    def test_ascii_row_width(self) -> None:
        inner_width = 40
        box_width = inner_width + 4
        row = self._build_preview_row("hello world", inner_width)
        assert _display_width(row) == box_width

    def test_cjk_row_width(self) -> None:
        inner_width = 40
        box_width = inner_width + 4
        row = self._build_preview_row("每个 skill 的问题完全贴合领域", inner_width)
        assert _display_width(row) == box_width

    def test_long_cjk_row_trimmed_to_box_width(self) -> None:
        inner_width = 20
        box_width = inner_width + 4
        long_text = "这是一段很长的中文文本用来测试截断功能是否正常工作"
        row = self._build_preview_row(long_text, inner_width)
        assert _display_width(row) == box_width

    def test_border_matches_content_rows(self) -> None:
        inner_width = 50
        box_width = inner_width + 4
        top_border = f"┌{'─' * (box_width - 2)}┐"
        bottom_border = f"└{'─' * (box_width - 2)}┘"

        lines = [
            "方案 A: 每个 skill 单独加问卷",
            "Plain ASCII line here",
            "混合 mixed 中英文 content 测试",
        ]

        assert _display_width(top_border) == box_width
        assert _display_width(bottom_border) == box_width
        for line in lines:
            row = self._build_preview_row(line, inner_width)
            assert _display_width(row) == box_width, f"Row width mismatch for: {line!r}"


class TestRenderMarkdownPreviewWidth:
    """Verify Rich-rendered lines respect inner_width in display columns."""

    def test_cjk_rendered_lines_fit_inner_width(self) -> None:
        md = "每个 skill 的问题完全贴合领域（PPT 问受众/页数/风格，信息图问布局/数据类型）skill 自包含不依赖系统提示词"
        inner_width = 40
        lines = _render_markdown_preview(md, inner_width)
        for line in lines:
            dw = _display_width(line)
            assert dw <= inner_width, f"Line exceeds inner_width ({dw} > {inner_width}): {line!r}"
