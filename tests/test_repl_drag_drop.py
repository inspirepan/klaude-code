from __future__ import annotations

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
