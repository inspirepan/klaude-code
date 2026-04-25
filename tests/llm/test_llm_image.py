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


def test_normalize_image_data_url_uses_jpeg_fallback_when_png_stays_above_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(image_module, "_MAX_IMAGE_SIZE_BYTES", 10_000_000)
    monkeypatch.setattr(image_module, "_IMAGE_TARGET_RAW_SIZE_BYTES", 5)
    png_bytes = b"\x89PNG\r\n\x1a\nlarge-png"
    original_url = f"data:image/png;base64,{b64encode(png_bytes).decode('ascii')}"

    def _fake_detect(_image_bytes: bytes, _mime_type: str) -> tuple[int, int]:
        return (80, 40)

    def _fake_reencode(
        _image_bytes: bytes,
        _mime_type: str,
        *,
        width: int | None = None,
        height: int | None = None,
        output_mime_type: str | None = None,
        quality: int = 85,
        quantize: bool = False,
    ) -> bytes | None:
        del width, height, quality, quantize
        if output_mime_type == "image/jpeg":
            return b"jpg"
        return b"larger-png"

    monkeypatch.setattr(image_module, "_detect_image_dimensions", _fake_detect)
    monkeypatch.setattr(image_module, "_pillow_reencode_image_bytes", _fake_reencode)

    normalized = image_module.normalize_image_data_url(original_url)
    assert normalized.startswith("data:image/jpeg;base64,")
    assert _payload_from_data_url(normalized) == b"jpg"


def test_normalize_image_data_url_uses_jpeg_fallback_when_gif_stays_above_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(image_module, "_MAX_IMAGE_SIZE_BYTES", 10_000_000)
    monkeypatch.setattr(image_module, "_IMAGE_TARGET_RAW_SIZE_BYTES", 5)
    gif_bytes = b"GIF89a" + (80).to_bytes(2, "little") + (40).to_bytes(2, "little") + b"large-gif"
    original_url = f"data:image/gif;base64,{b64encode(gif_bytes).decode('ascii')}"

    def _fake_reencode(
        _image_bytes: bytes,
        _mime_type: str,
        *,
        width: int | None = None,
        height: int | None = None,
        output_mime_type: str | None = None,
        quality: int = 85,
        quantize: bool = False,
    ) -> bytes | None:
        del width, height, quality, quantize
        if output_mime_type == "image/jpeg":
            return b"jpg"
        return None

    monkeypatch.setattr(image_module, "_pillow_reencode_image_bytes", _fake_reencode)

    normalized = image_module.normalize_image_data_url(original_url)
    assert normalized.startswith("data:image/jpeg;base64,")
    assert _payload_from_data_url(normalized) == b"jpg"


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


def test_image_file_to_data_url_keeps_frozen_file_stable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20
    path = tmp_path / "frozen.png"
    path.write_bytes(png_bytes)

    def _fail(_image_bytes: bytes, _mime_type: str, *, max_dimension: int = image_module.MAX_IMAGE_DIMENSION):
        raise AssertionError(f"frozen ImageFilePart should not be recompressed: {max_dimension}")

    monkeypatch.setattr(image_module, "_compress_image_bytes_for_request", _fail)

    result = image_module.image_file_to_data_url(
        message.ImageFilePart(file_path=str(path), mime_type="image/png", frozen=True),
        max_dimension=2000,
    )
    assert result is not None
    assert _payload_from_data_url(result) == png_bytes


def test_image_file_to_data_url_treats_existing_session_snapshot_as_stable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20
    path = tmp_path / ".klaude" / "projects" / "proj" / "sessions" / "sid" / "images" / "old.png"
    path.parent.mkdir(parents=True)
    path.write_bytes(png_bytes)

    def _fail(_image_bytes: bytes, _mime_type: str, *, max_dimension: int = image_module.MAX_IMAGE_DIMENSION):
        raise AssertionError(f"existing session snapshots should not be recompressed: {max_dimension}")

    monkeypatch.setattr(image_module, "_compress_image_bytes_for_request", _fail)

    result = image_module.image_file_to_data_url(
        message.ImageFilePart(file_path=str(path), mime_type="image/png"),
        max_dimension=2000,
    )
    assert result is not None
    assert _payload_from_data_url(result) == png_bytes


def test_freeze_image_for_history_converts_file_part_to_frozen_data_url(tmp_path: Path) -> None:
    png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20
    path = tmp_path / "history.png"
    path.write_bytes(png_bytes)

    frozen = image_module.freeze_image_for_history(
        message.ImageFilePart(file_path=str(path), mime_type="image/png"),
    )

    assert isinstance(frozen, message.ImageURLPart)
    assert frozen.frozen is True
    assert frozen.source_file_path == str(path)
    assert frozen.url.startswith("data:image/png;base64,")
    assert _payload_from_data_url(frozen.url) == png_bytes


def test_freeze_image_for_history_snapshots_file_when_images_dir_is_provided(tmp_path: Path) -> None:
    png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20
    path = tmp_path / "history.png"
    images_dir = tmp_path / "session-images"
    path.write_bytes(png_bytes)

    frozen = image_module.freeze_image_for_history(
        message.ImageFilePart(file_path=str(path), mime_type="image/png"),
        images_dir=images_dir,
    )

    assert isinstance(frozen, message.ImageFilePart)
    assert Path(frozen.file_path).is_relative_to(images_dir)
    assert Path(frozen.file_path).read_bytes() == png_bytes
    assert frozen.mime_type == "image/png"
    assert frozen.byte_size == len(png_bytes)
    assert frozen.sha256 is not None
    assert frozen.frozen is True


def test_freeze_image_for_history_snapshots_request_ready_bytes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    path = tmp_path / "history.png"
    images_dir = tmp_path / "session-images"
    path.write_bytes(b"raw-png")

    def _fake_compress(
        _image_bytes: bytes,
        _mime_type: str,
        *,
        max_dimension: int = image_module.MAX_IMAGE_DIMENSION,
    ) -> tuple[bytes, str]:
        assert max_dimension == image_module.MAX_IMAGE_DIMENSION
        return b"compressed", "image/jpeg"

    monkeypatch.setattr(image_module, "_compress_image_bytes_for_request", _fake_compress)

    frozen = image_module.freeze_image_for_history(
        message.ImageFilePart(file_path=str(path), mime_type="image/png"),
        images_dir=images_dir,
    )

    assert isinstance(frozen, message.ImageFilePart)
    assert Path(frozen.file_path).read_bytes() == b"compressed"
    assert frozen.mime_type == "image/jpeg"
    assert frozen.byte_size == len(b"compressed")
    assert frozen.frozen is True


def test_image_url_to_request_url_keeps_frozen_data_url(monkeypatch: pytest.MonkeyPatch) -> None:
    frozen = message.ImageURLPart(url="data:image/png;base64,abc123", frozen=True)

    def _fail(_url: str, *, max_dimension: int = image_module.MAX_IMAGE_DIMENSION) -> str:
        raise AssertionError(f"normalize_image_data_url should not be called for frozen images: {max_dimension}")

    monkeypatch.setattr(image_module, "normalize_image_data_url", _fail)

    assert image_module.image_url_to_request_url(frozen, max_dimension=2000) == frozen.url
