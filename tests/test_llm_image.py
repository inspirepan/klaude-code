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
    assert _payload_from_data_url(result) == b"small"


def test_image_file_to_data_url_keeps_image_when_size_within_limit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(image_module, "_MAX_IMAGE_SIZE_BYTES", 16)

    path = tmp_path / "img.png"
    path.write_bytes(b"0123456789ABCDEF")

    called = False

    def _fake_detect(_image_bytes: bytes, _mime_type: str) -> tuple[int, int]:
        nonlocal called
        called = True
        return (1, 1)

    monkeypatch.setattr(image_module, "_detect_image_dimensions", _fake_detect)

    result = image_module.image_file_to_data_url(
        message.ImageFilePart(file_path=str(path), mime_type="image/png"),
    )
    assert _payload_from_data_url(result) == b"0123456789ABCDEF"
    assert called is False


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


def test_normalize_image_data_url_keeps_non_image_media_type(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(image_module, "_MAX_IMAGE_SIZE_BYTES", 10)
    original_url = f"data:text/plain;base64,{b64encode(b'0123456789ABCDEF').decode('ascii')}"

    normalized = image_module.normalize_image_data_url(original_url)
    assert normalized == original_url


def test_normalize_image_data_url_keeps_non_data_url() -> None:
    url = "https://example.com/demo.png"
    assert image_module.normalize_image_data_url(url) == url
