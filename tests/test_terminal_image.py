from __future__ import annotations

import io
import os
import subprocess
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


def test_print_kitty_image_converts_svg(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    svg_path = tmp_path / "render-mermaid-arch.svg"
    svg_path.write_text('<svg xmlns="http://www.w3.org/2000/svg"></svg>')

    convert_calls: list[Path] = []
    write_calls: list[str] = []

    def _convert_to_png(path: Path) -> bytes | None:
        convert_calls.append(path)
        return _png_bytes()

    def _write_kitty_graphics(out: io.StringIO, encoded_data: str, *, size_param: str) -> None:
        write_calls.append(size_param)

    monkeypatch.setattr(terminal_image, "_convert_to_png", _convert_to_png)
    monkeypatch.setattr(terminal_image, "_write_kitty_graphics", _write_kitty_graphics)

    terminal_image.print_kitty_image(svg_path, file=io.StringIO())

    assert convert_calls == [svg_path]
    assert write_calls == [""]


def test_convert_to_png_svg_prefers_qlmanage(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    svg_path = tmp_path / "render-mermaid-arch.svg"
    svg_path.write_text('<svg xmlns="http://www.w3.org/2000/svg"></svg>')
    png = _png_bytes()
    calls: list[list[str]] = []

    def _run(cmd: list[str], capture_output: bool) -> subprocess.CompletedProcess[bytes]:
        calls.append(cmd)
        if cmd[0] != "qlmanage":
            raise AssertionError(f"unexpected command: {cmd[0]}")
        out_dir = Path(cmd[cmd.index("-o") + 1])
        (out_dir / f"{svg_path.name}.png").write_bytes(png)
        return subprocess.CompletedProcess(cmd, returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr(terminal_image.subprocess, "run", _run)

    converted = terminal_image._convert_to_png(svg_path)  # pyright: ignore[reportPrivateUsage]

    assert converted == png
    assert len(calls) == 1
    assert calls[0][:5] == ["qlmanage", "-t", "-s", "1024", "-o"]
    assert calls[0][-1] == str(svg_path)


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


def test_convert_to_png_svg_falls_back_when_thumbnail_is_cropped(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    svg_path = tmp_path / "article-illustrator-flow.svg"
    svg_path.write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 320 3200"></svg>')

    ql_png = _png_bytes(width=1024, height=1024)
    sips_png = _png_bytes(width=320, height=3200)
    calls: list[str] = []

    def _run(cmd: list[str], capture_output: bool) -> subprocess.CompletedProcess[bytes]:
        calls.append(cmd[0])
        if cmd[0] == "qlmanage":
            out_dir = Path(cmd[cmd.index("-o") + 1])
            (out_dir / f"{svg_path.name}.png").write_bytes(ql_png)
            return subprocess.CompletedProcess(cmd, returncode=0, stdout=b"", stderr=b"")
        if cmd[0] == "sips":
            out_path = Path(cmd[cmd.index("--out") + 1])
            out_path.write_bytes(sips_png)
            return subprocess.CompletedProcess(cmd, returncode=0, stdout=b"", stderr=b"")
        raise AssertionError(f"unexpected command: {cmd[0]}")

    monkeypatch.setattr(terminal_image.subprocess, "run", _run)

    converted = terminal_image._convert_to_png(svg_path)  # pyright: ignore[reportPrivateUsage]

    assert converted == sips_png
    assert calls[:2] == ["qlmanage", "sips"]


def test_normalize_svg_for_sips_scales_root_dimensions() -> None:
    svg = '<svg xmlns="http://www.w3.org/2000/svg" width="300" height="1200" viewBox="0 0 300 1200"></svg>'

    normalized = terminal_image._normalize_svg_for_sips(svg)  # pyright: ignore[reportPrivateUsage]

    assert 'width="600"' in normalized
    assert 'height="2400"' in normalized


def test_expand_svg_text_tspans_converts_multiline_text() -> None:
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg">'
        '<text x="100" y="200" text-anchor="middle" font-size="13">'
        '<tspan x="100" dy="-3.9">line1</tspan>'
        '<tspan x="100" dy="16.9">line2</tspan>'
        "</text>"
        "</svg>"
    )

    expanded = terminal_image._expand_svg_text_tspans(svg)  # pyright: ignore[reportPrivateUsage]

    assert "<tspan" not in expanded
    assert expanded.count("<text ") == 2
    assert 'x="100" y="196.1"' in expanded
    assert 'x="100" y="213"' in expanded


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
