from __future__ import annotations

import io
import os
from pathlib import Path

import pytest

from klaude_code.tui.terminal import image as terminal_image


def _png_bytes(width: int = 18, height: int = 18) -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n"
        b"\x00\x00\x00\rIHDR"
        + width.to_bytes(4, "big")
        + height.to_bytes(4, "big")
        + b"\x08\x02\x00\x00\x00"
        + b"\x00\x00\x00\x00"
    )


def test_print_kitty_image_skips_svg_without_png_bytes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    svg_path = tmp_path / "render-mermaid-arch.svg"
    svg_path.write_text('<svg xmlns="http://www.w3.org/2000/svg"></svg>')

    def _convert_to_png(path: Path) -> bytes | None:
        raise AssertionError("conversion should not be called for svg files")

    def _write_kitty_graphics(out: io.StringIO, encoded_data: str, *, size_param: str) -> None:
        raise AssertionError("svg files should not be rendered via kitty graphics")

    output = io.StringIO()
    monkeypatch.setattr(terminal_image, "_convert_to_png", _convert_to_png)
    monkeypatch.setattr(terminal_image, "_write_kitty_graphics", _write_kitty_graphics)

    terminal_image.print_kitty_image(svg_path, file=output)

    assert output.getvalue().strip() == f"[[Image: {svg_path}]]"


def test_print_kitty_image_skips_conversion_for_png_bytes_with_svg_suffix(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake_svg = tmp_path / "flow.svg"
    fake_svg.write_bytes(_png_bytes())

    write_calls: list[str] = []

    def _write_kitty_graphics(out: io.StringIO, encoded_data: str, *, size_param: str) -> None:
        write_calls.append(size_param)

    def _convert_to_png(path: Path) -> bytes | None:
        raise AssertionError("conversion should not be called for png bytes")

    monkeypatch.setattr(terminal_image, "_write_kitty_graphics", _write_kitty_graphics)
    monkeypatch.setattr(terminal_image, "_convert_to_png", _convert_to_png)

    terminal_image.print_kitty_image(fake_svg, file=io.StringIO())

    assert write_calls == [""]


def test_print_kitty_image_expands_rows_for_tall_image_readability(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    png_path = tmp_path / "tall.png"
    png_path.write_bytes(_png_bytes(width=303, height=1219))

    size_params: list[str] = []

    def _write_kitty_graphics(out: io.StringIO, encoded_data: str, *, size_param: str) -> None:
        size_params.append(size_param)

    monkeypatch.setattr(terminal_image, "_write_kitty_graphics", _write_kitty_graphics)
    monkeypatch.setattr(terminal_image.shutil, "get_terminal_size", lambda: os.terminal_size((80, 24)))

    terminal_image.print_kitty_image(png_path, file=io.StringIO())

    assert size_params == ["c=50"]
