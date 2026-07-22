from __future__ import annotations

import io
import os
from pathlib import Path

import pytest

from klaude_code.tui.terminal import image as terminal_image

# Captured before the autouse fixture stubs the module attribute.
_REAL_FILE_TRANSMISSION_DETECTION = terminal_image._supports_kitty_file_transmission  # pyright: ignore[reportPrivateUsage]


@pytest.fixture(autouse=True)
def _force_kitty_support(monkeypatch: pytest.MonkeyPatch) -> None:  # pyright: ignore[reportUnusedFunction]
    """Ensure existing tests run as if Kitty graphics is supported."""
    monkeypatch.setattr(terminal_image, "supports_kitty_graphics", lambda: True)
    # Exercise the inline transmission path by default; the file-based medium
    # (dependent on the host TERM/SSH env) has dedicated tests below.
    monkeypatch.setattr(terminal_image, "_supports_kitty_file_transmission", lambda: False)


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


def test_print_kitty_image_falls_back_when_unsupported(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    png_path = tmp_path / "photo.png"
    png_path.write_bytes(_png_bytes())

    monkeypatch.setattr(terminal_image, "supports_kitty_graphics", lambda: False)

    def _write_kitty_graphics(out: io.StringIO, encoded_data: str, *, size_param: str) -> None:
        raise AssertionError("should not render kitty graphics on unsupported terminal")

    monkeypatch.setattr(terminal_image, "_write_kitty_graphics", _write_kitty_graphics)

    output = io.StringIO()
    terminal_image.print_kitty_image(png_path, file=output)

    assert output.getvalue().strip() == f"[[Image: {png_path}]]"


def test_print_kitty_image_uses_file_transmission_when_supported(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    png_path = tmp_path / "photo.png"
    png_path.write_bytes(_png_bytes())

    monkeypatch.setattr(terminal_image, "_supports_kitty_file_transmission", lambda: True)

    def _write_kitty_graphics(out: io.StringIO, encoded_data: str, *, size_param: str) -> None:
        raise AssertionError("inline transmission should not be used when file medium is available")

    monkeypatch.setattr(terminal_image, "_write_kitty_graphics", _write_kitty_graphics)

    output = io.StringIO()
    terminal_image.print_kitty_image(png_path, file=output)

    payload = output.getvalue()
    assert "\033_G" in payload and "t=f" in payload and payload.endswith("\n")
    # The escape sequence carries a base64 path, not the image bytes.
    control_and_data = payload.split("\033_G", 1)[1].split("\033\\", 1)[0]
    encoded_path = control_and_data.split(";", 1)[1]
    import base64

    tmp_file = Path(base64.standard_b64decode(encoded_path).decode("utf-8"))
    assert tmp_file.exists()
    assert tmp_file.read_bytes() == _png_bytes()
    tmp_file.unlink()


def test_kitty_file_transmission_detection(monkeypatch: pytest.MonkeyPatch) -> None:
    detect = _REAL_FILE_TRANSMISSION_DETECTION
    monkeypatch.delenv("SSH_TTY", raising=False)
    monkeypatch.delenv("SSH_CONNECTION", raising=False)
    monkeypatch.setenv("TERM_PROGRAM", "ghostty")
    monkeypatch.setenv("TERM", "xterm-256color")
    assert detect()

    monkeypatch.setenv("SSH_CONNECTION", "10.0.0.1 1 10.0.0.2 22")
    assert not detect()

    monkeypatch.delenv("SSH_CONNECTION", raising=False)
    monkeypatch.setenv("TERM_PROGRAM", "WezTerm")
    assert not detect()
