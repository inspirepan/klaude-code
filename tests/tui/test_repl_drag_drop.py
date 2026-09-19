from __future__ import annotations

import shlex
from pathlib import Path

from klaude_code.tui.input.drag_drop import convert_dropped_text
from klaude_code.tui.input.images import extract_images_from_text, format_image_marker


def test_convert_file_uri_to_at_token(tmp_path: Path) -> None:
    f = tmp_path / "a.txt"
    f.write_text("hi", encoding="utf-8")

    out = convert_dropped_text(f.as_uri(), cwd=tmp_path)
    assert out == "@a.txt"


def test_convert_file_uri_with_spaces_is_quoted(tmp_path: Path) -> None:
    f = tmp_path / "my file.txt"
    f.write_text("hi", encoding="utf-8")

    out = convert_dropped_text(f.as_uri(), cwd=tmp_path)
    assert out == '@"my file.txt"'


def test_convert_image_file_uri_to_image_tag(tmp_path: Path) -> None:
    img = tmp_path / "x.png"
    img.write_bytes(b"not-a-real-png")

    out = convert_dropped_text(img.as_uri(), cwd=tmp_path)
    assert out == format_image_marker("x.png")


def test_plain_paths_not_converted(tmp_path: Path) -> None:
    """Plain paths should not be auto-converted to @ tokens."""
    a = tmp_path / "a.txt"
    b = tmp_path / "b.txt"
    a.write_text("a", encoding="utf-8")
    b.write_text("b", encoding="utf-8")

    pasted = f"{a} {b}"
    out = convert_dropped_text(pasted, cwd=tmp_path)
    # Plain paths are returned unchanged
    assert out == pasted


def test_extract_images_from_marker(tmp_path: Path) -> None:
    img = tmp_path / "x.jpg"
    img.write_bytes(b"\xff\xd8\xff")

    marker = format_image_marker(str(img))
    images = extract_images_from_text(f"hello {marker}")
    assert len(images) == 1
    assert images[0].file_path == str(img)
    assert images[0].mime_type == "image/jpeg"


def test_path_list_converted_when_allowed(tmp_path: Path) -> None:
    a = tmp_path / "a.txt"
    b = tmp_path / "b.txt"
    a.write_text("a", encoding="utf-8")
    b.write_text("b", encoding="utf-8")

    out = convert_dropped_text(f"{a} {b}", cwd=tmp_path, allow_path_lists=True)
    assert out == "@a.txt @b.txt"


def test_escaped_path_converted_when_allowed(tmp_path: Path) -> None:
    """Terminals that drop an escaped path instead of a file:// URI."""

    f = tmp_path / "my file.txt"
    f.write_text("hi", encoding="utf-8")

    out = convert_dropped_text(shlex.quote(str(f)), cwd=tmp_path, allow_path_lists=True)
    assert out == '@"my file.txt"'


def test_trailing_newline_is_dropped_for_path_lists(tmp_path: Path) -> None:
    f = tmp_path / "a.txt"
    f.write_text("hi", encoding="utf-8")

    out = convert_dropped_text(f"{f}\n", cwd=tmp_path, allow_path_lists=True)
    assert out == "@a.txt"


def test_trailing_newline_is_dropped_for_file_uris(tmp_path: Path) -> None:
    f = tmp_path / "a.txt"
    f.write_text("hi", encoding="utf-8")

    out = convert_dropped_text(f"{f.as_uri()}\n", cwd=tmp_path)
    assert out == "@a.txt"


def test_image_path_list_converted_when_allowed(tmp_path: Path) -> None:
    img = tmp_path / "x.png"
    img.write_bytes(b"not-a-real-png")

    out = convert_dropped_text(str(img), cwd=tmp_path, allow_path_lists=True)
    assert out == format_image_marker("x.png")


def test_missing_paths_stay_untouched_even_when_allowed(tmp_path: Path) -> None:
    out = convert_dropped_text("no such file here", cwd=tmp_path, allow_path_lists=True)
    assert out == "no such file here"


def test_unexpandable_tilde_token_stays_untouched(tmp_path: Path) -> None:
    """`~nosuchuser` makes Path.expanduser() raise RuntimeError."""

    pasted = "~nosuchuser12345/x.txt"
    out = convert_dropped_text(pasted, cwd=tmp_path, allow_path_lists=True)
    assert out == pasted


def test_existing_syntax_is_not_reconverted(tmp_path: Path) -> None:
    f = tmp_path / "a.txt"
    f.write_text("hi", encoding="utf-8")

    out = convert_dropped_text(f"@a.txt {f}", cwd=tmp_path, allow_path_lists=True)
    assert out == f"@a.txt {f}"
