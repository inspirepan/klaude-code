from __future__ import annotations

from base64 import b64decode, b64encode
from pathlib import Path

import pytest

from klaude_code.llm import image as image_module
from klaude_code.protocol import message


def _payload_from_data_url(data_url: str) -> bytes:
    return b64decode(data_url.split(",", 1)[1])


def test_image_file_to_data_url_resizes_when_size_exceeds_limit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(image_module, "_MAX_IMAGE_SIZE_BYTES", 10)

    path = tmp_path / "img.png"
    path.write_bytes(b"0123456789ABCDEF")

    def _fake_detect(_image_bytes: bytes, _mime_type: str) -> tuple[int, int]:
        return (200, 100)

    def _fake_resize(_image_bytes: bytes, _mime_type: str, *, width: int, height: int) -> bytes:
        expected_scale = (10 / 16) ** 0.5
        expected_scale *= 0.9
        assert width == int(200 * expected_scale)
        assert height == int(100 * expected_scale)
        return b"small"

    monkeypatch.setattr(image_module, "_detect_image_dimensions", _fake_detect)
    monkeypatch.setattr(image_module, "_resize_image_bytes", _fake_resize)

    result = image_module.image_file_to_data_url(
        message.ImageFilePart(file_path=str(path), mime_type="image/png"),
    )
    assert result is not None
    assert _payload_from_data_url(result) == b"small"


def test_image_file_to_data_url_keeps_image_when_size_within_limit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(image_module, "_MAX_IMAGE_SIZE_BYTES", 16)

    path = tmp_path / "img.png"
    path.write_bytes(b"0123456789ABCDEF")

    def _fake_detect(_image_bytes: bytes, _mime_type: str) -> tuple[int, int]:
        return (1, 1)

    monkeypatch.setattr(image_module, "_detect_image_dimensions", _fake_detect)

    result = image_module.image_file_to_data_url(
        message.ImageFilePart(file_path=str(path), mime_type="image/png"),
    )
    assert result is not None
    assert _payload_from_data_url(result) == b"0123456789ABCDEF"


def test_normalize_image_data_url_resizes_large_inline_image(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(image_module, "_MAX_IMAGE_SIZE_BYTES", 10)
    original_url = f"data:image/png;base64,{b64encode(b'0123456789ABCDEF').decode('ascii')}"

    def _fake_detect(_image_bytes: bytes, _mime_type: str) -> tuple[int, int]:
        return (80, 40)

    def _fake_resize(_image_bytes: bytes, _mime_type: str, *, width: int, height: int) -> bytes:
        expected_scale = (10 / 16) ** 0.5
        expected_scale *= 0.9
        assert width == int(80 * expected_scale)
        assert height == int(40 * expected_scale)
        return b"tiny"

    monkeypatch.setattr(image_module, "_detect_image_dimensions", _fake_detect)
    monkeypatch.setattr(image_module, "_resize_image_bytes", _fake_resize)

    normalized = image_module.normalize_image_data_url(original_url)
    assert _payload_from_data_url(normalized) == b"tiny"


def test_normalize_image_data_url_resizes_when_base64_payload_exceeds_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(image_module, "_MAX_IMAGE_SIZE_BYTES", 100)
    monkeypatch.setattr(image_module, "_MAX_BASE64_IMAGE_SIZE_BYTES", 20)
    original_url = f"data:image/png;base64,{b64encode(b'0123456789ABCDEF').decode('ascii')}"

    def _fake_detect(_image_bytes: bytes, _mime_type: str) -> tuple[int, int]:
        return (80, 40)

    def _fake_resize(_image_bytes: bytes, _mime_type: str, *, width: int, height: int) -> bytes:
        expected_scale = (15 / 16) ** 0.5
        expected_scale *= 0.9
        assert width == int(80 * expected_scale)
        assert height == int(40 * expected_scale)
        return b"tiny"

    monkeypatch.setattr(image_module, "_detect_image_dimensions", _fake_detect)
    monkeypatch.setattr(image_module, "_resize_image_bytes", _fake_resize)

    normalized = image_module.normalize_image_data_url(original_url)
    assert _payload_from_data_url(normalized) == b"tiny"
    assert len(normalized.split(",", 1)[1]) <= 20


def test_normalize_image_data_url_keeps_non_image_media_type(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(image_module, "_MAX_IMAGE_SIZE_BYTES", 10)
    original_url = f"data:text/plain;base64,{b64encode(b'0123456789ABCDEF').decode('ascii')}"

    normalized = image_module.normalize_image_data_url(original_url)
    assert normalized == original_url


def test_normalize_image_data_url_keeps_non_data_url() -> None:
    url = "https://example.com/demo.png"
    assert image_module.normalize_image_data_url(url) == url


# --- detect_mime_type_from_bytes ---


def test_detect_mime_type_from_bytes_png() -> None:
    assert image_module.detect_mime_type_from_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16) == "image/png"


def test_detect_mime_type_from_bytes_jpeg() -> None:
    assert image_module.detect_mime_type_from_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 10) == "image/jpeg"


def test_detect_mime_type_from_bytes_gif87a() -> None:
    assert image_module.detect_mime_type_from_bytes(b"GIF87a" + b"\x00" * 10) == "image/gif"


def test_detect_mime_type_from_bytes_gif89a() -> None:
    assert image_module.detect_mime_type_from_bytes(b"GIF89a" + b"\x00" * 10) == "image/gif"


def test_detect_mime_type_from_bytes_webp() -> None:
    assert image_module.detect_mime_type_from_bytes(b"RIFF\x00\x00\x00\x00WEBP" + b"\x00" * 20) == "image/webp"


def test_detect_mime_type_from_bytes_unknown() -> None:
    assert image_module.detect_mime_type_from_bytes(b"not an image") is None


def test_detect_mime_type_from_bytes_empty() -> None:
    assert image_module.detect_mime_type_from_bytes(b"") is None


# --- MIME type correction ---


def test_normalize_image_data_url_corrects_wrong_mime(monkeypatch: pytest.MonkeyPatch) -> None:
    """A PNG image declared as image/jpeg should be corrected to image/png."""
    monkeypatch.setattr(image_module, "_MAX_IMAGE_SIZE_BYTES", 10_000_000)
    png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20
    wrong_url = f"data:image/jpeg;base64,{b64encode(png_bytes).decode('ascii')}"

    corrected = image_module.normalize_image_data_url(wrong_url)
    assert corrected.startswith("data:image/png;base64,")
    assert _payload_from_data_url(corrected) == png_bytes


def test_resize_image_bytes_if_needed_downscales_oversized_dimensions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An image with a dimension exceeding 8000px should be downscaled."""
    monkeypatch.setattr(image_module, "_MAX_IMAGE_SIZE_BYTES", 10_000_000)

    resize_calls: list[tuple[int, int]] = []

    def _fake_detect(image_bytes: bytes, _mime_type: str) -> tuple[int, int]:
        if image_bytes == b"resized":
            return (8000, 4000)
        return (16000, 8000)

    def _fake_resize(_image_bytes: bytes, _mime_type: str, *, width: int, height: int) -> bytes:
        resize_calls.append((width, height))
        return b"resized"

    monkeypatch.setattr(image_module, "_detect_image_dimensions", _fake_detect)
    monkeypatch.setattr(image_module, "_resize_image_bytes", _fake_resize)

    result = image_module._resize_image_bytes_if_needed(b"large-image", "image/png")  # pyright: ignore[reportPrivateUsage]
    assert result == b"resized"
    assert len(resize_calls) == 1
    # scale = min(8000/16000, 8000/8000) = 0.5
    assert resize_calls[0] == (8000, 4000)


def test_resize_image_bytes_if_needed_uses_custom_max_dimension(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """max_dimension=2000 should downscale a 4000x3000 image."""
    monkeypatch.setattr(image_module, "_MAX_IMAGE_SIZE_BYTES", 10_000_000)

    resize_calls: list[tuple[int, int]] = []

    def _fake_detect(image_bytes: bytes, _mime_type: str) -> tuple[int, int]:
        if image_bytes == b"resized":
            return (2000, 1500)
        return (4000, 3000)

    def _fake_resize(_image_bytes: bytes, _mime_type: str, *, width: int, height: int) -> bytes:
        resize_calls.append((width, height))
        return b"resized"

    monkeypatch.setattr(image_module, "_detect_image_dimensions", _fake_detect)
    monkeypatch.setattr(image_module, "_resize_image_bytes", _fake_resize)

    result = image_module._resize_image_bytes_if_needed(  # pyright: ignore[reportPrivateUsage]
        b"large-image", "image/png", max_dimension=2000
    )
    assert result == b"resized"
    assert len(resize_calls) == 1
    # scale = min(2000/4000, 2000/3000) = 0.5
    assert resize_calls[0] == (2000, 1500)


def test_resize_image_bytes_if_needed_skips_within_dimension_limits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An image within both size and dimension limits should not be resized."""
    monkeypatch.setattr(image_module, "_MAX_IMAGE_SIZE_BYTES", 10_000_000)

    def _fake_detect(_image_bytes: bytes, _mime_type: str) -> tuple[int, int]:
        return (4000, 3000)

    monkeypatch.setattr(image_module, "_detect_image_dimensions", _fake_detect)

    original = b"small-image"
    result = image_module._resize_image_bytes_if_needed(original, "image/png")  # pyright: ignore[reportPrivateUsage]
    assert result is original


def test_image_file_to_data_url_corrects_wrong_extension(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A PNG file with .jpg extension should produce a data URL with image/png."""
    monkeypatch.setattr(image_module, "_MAX_IMAGE_SIZE_BYTES", 10_000_000)
    png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20
    path = tmp_path / "photo.jpg"
    path.write_bytes(png_bytes)

    result = image_module.image_file_to_data_url(
        message.ImageFilePart(file_path=str(path), mime_type="image/jpeg"),
    )
    assert result is not None
    assert result.startswith("data:image/png;base64,")
    assert _payload_from_data_url(result) == png_bytes
