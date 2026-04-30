"""Image processing utilities for LLM responses.

This module provides reusable image handling primitives that can be shared
across different LLM providers and protocols (OpenAI, Anthropic, etc.).
"""

from __future__ import annotations

import hashlib
import mimetypes
import shutil
import subprocess
import sys
import tempfile
from base64 import b64decode, b64encode
from binascii import Error as BinasciiError
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

from klaude_code.protocol import message

_MAX_IMAGE_SIZE_BYTES = 4_500_000
_MAX_BASE64_IMAGE_SIZE_BYTES = 5 * 1024 * 1024
_IMAGE_TARGET_RAW_SIZE_BYTES = (_MAX_BASE64_IMAGE_SIZE_BYTES // 4) * 3
MAX_IMAGE_DIMENSION = 8000
_JPEG_FALLBACK_QUALITIES = (85, 70, 55, 40, 25)
_JPEG_SOF_MARKERS = {
    0xC0,
    0xC1,
    0xC2,
    0xC3,
    0xC5,
    0xC6,
    0xC7,
    0xC9,
    0xCA,
    0xCB,
    0xCD,
    0xCE,
    0xCF,
}


def _suffix_for_mime_type(mime_type: str) -> str | None:
    mapping = {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/gif": ".gif",
        "image/webp": ".webp",
    }
    return mapping.get(mime_type.lower())


def _parse_png_dimensions(data: bytes) -> tuple[int, int] | None:
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        return None
    width = int.from_bytes(data[16:20], "big")
    height = int.from_bytes(data[20:24], "big")
    if width <= 0 or height <= 0:
        return None
    return width, height


def _parse_gif_dimensions(data: bytes) -> tuple[int, int] | None:
    if len(data) < 10 or (not data.startswith(b"GIF87a") and not data.startswith(b"GIF89a")):
        return None
    width = int.from_bytes(data[6:8], "little")
    height = int.from_bytes(data[8:10], "little")
    if width <= 0 or height <= 0:
        return None
    return width, height


def _parse_webp_dimensions(data: bytes) -> tuple[int, int] | None:
    if len(data) < 30 or data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        return None

    chunk = data[12:16]
    if chunk == b"VP8X":
        width = 1 + int.from_bytes(data[24:27], "little")
        height = 1 + int.from_bytes(data[27:30], "little")
        return (width, height) if width > 0 and height > 0 else None

    if chunk == b"VP8L" and len(data) >= 25:
        b0, b1, b2, b3 = data[21], data[22], data[23], data[24]
        width = 1 + (((b1 & 0x3F) << 8) | b0)
        height = 1 + (((b3 & 0x0F) << 10) | (b2 << 2) | ((b1 & 0xC0) >> 6))
        return (width, height) if width > 0 and height > 0 else None

    return None


def _parse_jpeg_dimensions(data: bytes) -> tuple[int, int] | None:
    if len(data) < 4 or data[0] != 0xFF or data[1] != 0xD8:
        return None

    i = 2
    while i + 9 < len(data):
        while i < len(data) and data[i] != 0xFF:
            i += 1
        if i + 1 >= len(data):
            return None

        while i < len(data) and data[i] == 0xFF:
            i += 1
        if i >= len(data):
            return None

        marker = data[i]
        i += 1

        if marker in {0xD8, 0xD9}:
            continue
        if marker == 0x01 or 0xD0 <= marker <= 0xD7:
            continue

        if i + 1 >= len(data):
            return None
        segment_len = int.from_bytes(data[i : i + 2], "big")
        if segment_len < 2 or i + segment_len > len(data):
            return None

        if marker in _JPEG_SOF_MARKERS:
            if segment_len < 7:
                return None
            height = int.from_bytes(data[i + 3 : i + 5], "big")
            width = int.from_bytes(data[i + 5 : i + 7], "big")
            if width <= 0 or height <= 0:
                return None
            return width, height

        i += segment_len

    return None


def detect_mime_type_from_bytes(data: bytes) -> str | None:
    """Detect image MIME type from magic bytes, returning None for unrecognized formats."""
    if len(data) >= 8 and data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if len(data) >= 3 and data[0] == 0xFF and data[1] == 0xD8 and data[2] == 0xFF:
        return "image/jpeg"
    if len(data) >= 6 and (data[:6] == b"GIF87a" or data[:6] == b"GIF89a"):
        return "image/gif"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def _detect_image_dimensions(image_bytes: bytes, mime_type: str) -> tuple[int, int] | None:
    media = mime_type.lower()
    if media == "image/png":
        return _parse_png_dimensions(image_bytes)
    if media in {"image/jpeg", "image/jpg"}:
        return _parse_jpeg_dimensions(image_bytes)
    if media == "image/gif":
        return _parse_gif_dimensions(image_bytes)
    if media == "image/webp":
        return _parse_webp_dimensions(image_bytes)
    return None


def _resize_image_macos(input_path: Path, output_path: Path, *, width: int, height: int) -> bool:
    try:
        result = subprocess.run(
            ["sips", "-z", str(height), str(width), str(input_path), "--out", str(output_path)],
            capture_output=True,
        )
    except OSError:
        return False
    return result.returncode == 0 and output_path.exists() and output_path.stat().st_size > 0


def _resize_image_linux(input_path: Path, output_path: Path, *, width: int, height: int) -> bool:
    if shutil.which("convert") is None:
        return False
    try:
        result = subprocess.run(
            ["convert", str(input_path), "-resize", f"{width}x{height}!", str(output_path)],
            capture_output=True,
        )
    except OSError:
        return False
    return result.returncode == 0 and output_path.exists() and output_path.stat().st_size > 0


def _resize_image_windows(input_path: Path, output_path: Path, *, width: int, height: int, mime_type: str) -> bool:
    image_format = {
        "image/png": "Png",
        "image/jpeg": "Jpeg",
        "image/jpg": "Jpeg",
        "image/gif": "Gif",
    }.get(mime_type.lower())
    if image_format is None:
        return False

    script = f'''
    Add-Type -AssemblyName System.Drawing
    $img = [System.Drawing.Image]::FromFile("{input_path}")
    $bmp = New-Object System.Drawing.Bitmap({width}, {height})
    $graphics = [System.Drawing.Graphics]::FromImage($bmp)
    $graphics.DrawImage($img, 0, 0, {width}, {height})
    $img.Dispose()
    $bmp.Save("{output_path}", [System.Drawing.Imaging.ImageFormat]::{image_format})
    $bmp.Dispose()
    $graphics.Dispose()
    Write-Output "ok"
    '''
    try:
        result = subprocess.run(["powershell", "-Command", script], capture_output=True, text=True)
    except OSError:
        return False
    return result.returncode == 0 and "ok" in result.stdout and output_path.exists() and output_path.stat().st_size > 0


def _flatten_for_jpeg(image: Image.Image) -> Image.Image:
    if image.mode in {"RGBA", "LA"} or "transparency" in image.info:
        rgba = image.convert("RGBA")
        background = Image.new("RGB", rgba.size, (255, 255, 255))
        background.paste(rgba, mask=rgba.getchannel("A"))
        return background
    return image.convert("RGB")


def _pillow_reencode_image_bytes(
    image_bytes: bytes,
    mime_type: str,
    *,
    width: int | None = None,
    height: int | None = None,
    output_mime_type: str | None = None,
    quality: int = 85,
    quantize: bool = False,
) -> bytes | None:
    output_mime = (output_mime_type or mime_type).lower()
    try:
        with Image.open(BytesIO(image_bytes)) as opened:
            image = ImageOps.exif_transpose(opened)
            if width is not None and height is not None and image.size != (width, height):
                image = image.resize((width, height), Image.Resampling.LANCZOS)

            output = BytesIO()
            if output_mime == "image/png":
                png_image = image
                if quantize and image.mode not in {"RGBA", "LA"} and "transparency" not in image.info:
                    png_image = image.convert("RGB").quantize(colors=256)
                png_image.save(output, format="PNG", optimize=True, compress_level=9)
            elif output_mime in {"image/jpeg", "image/jpg"}:
                _flatten_for_jpeg(image).save(
                    output,
                    format="JPEG",
                    quality=quality,
                    optimize=True,
                    progressive=True,
                )
            elif output_mime == "image/webp":
                image.save(output, format="WEBP", quality=quality, method=6)
            else:
                return None
            return output.getvalue()
    except (OSError, UnidentifiedImageError, ValueError):
        return None


def _resize_image_bytes(image_bytes: bytes, mime_type: str, *, width: int, height: int) -> bytes | None:
    pillow_resized = _pillow_reencode_image_bytes(image_bytes, mime_type, width=width, height=height)
    if pillow_resized is not None:
        return pillow_resized

    suffix = _suffix_for_mime_type(mime_type)
    if suffix is None:
        return None

    with tempfile.TemporaryDirectory(prefix="klaude-img-") as tmp_dir:
        input_path = Path(tmp_dir) / f"input{suffix}"
        output_path = Path(tmp_dir) / f"output{suffix}"
        input_path.write_bytes(image_bytes)

        if sys.platform == "darwin":
            ok = _resize_image_macos(input_path, output_path, width=width, height=height)
        elif sys.platform == "win32":
            ok = _resize_image_windows(input_path, output_path, width=width, height=height, mime_type=mime_type)
        else:
            ok = _resize_image_linux(input_path, output_path, width=width, height=height)

        if not ok:
            return None
        return output_path.read_bytes()


def _base64_size_bytes(decoded_size_bytes: int) -> int:
    return ((decoded_size_bytes + 2) // 3) * 4


def _max_inline_image_size_bytes() -> int:
    return min(_MAX_IMAGE_SIZE_BYTES, (_MAX_BASE64_IMAGE_SIZE_BYTES // 4) * 3, _IMAGE_TARGET_RAW_SIZE_BYTES)


def _image_bytes_within_limits(image_bytes: bytes) -> bool:
    size_bytes = len(image_bytes)
    return size_bytes <= _MAX_IMAGE_SIZE_BYTES and _base64_size_bytes(size_bytes) <= _MAX_BASE64_IMAGE_SIZE_BYTES


def _image_dimensions_within_limit(image_bytes: bytes, mime_type: str, max_dimension: int) -> bool:
    dims = _detect_image_dimensions(image_bytes, mime_type)
    return dims is None or (dims[0] <= max_dimension and dims[1] <= max_dimension)


def _same_image_mime_type(left: str, right: str) -> bool:
    normalized = {left.lower(), right.lower()}
    return len(normalized) == 1 or normalized == {"image/jpeg", "image/jpg"}


def _data_url_within_request_limits(url: str, *, max_dimension: int) -> bool:
    try:
        mime_type, base64_payload, decoded = parse_data_url(url)
    except ValueError:
        return True

    detected = detect_mime_type_from_bytes(decoded)
    media_type = detected or mime_type
    return (
        (detected is None or _same_image_mime_type(mime_type, detected))
        and _image_bytes_within_limits(decoded)
        and len(base64_payload.encode("ascii")) <= _MAX_BASE64_IMAGE_SIZE_BYTES
        and _image_dimensions_within_limit(decoded, media_type, max_dimension)
    )


def image_data_url_within_single_image_limits(url: str) -> bool:
    """Return whether a data URL fits the provider-facing single-image size limits."""

    if not url.startswith("data:"):
        return True
    try:
        _, base64_payload, decoded = parse_data_url(url)
    except ValueError:
        return False
    return _image_bytes_within_limits(decoded) and len(base64_payload.encode("ascii")) <= _MAX_BASE64_IMAGE_SIZE_BYTES


def _image_bytes_within_target(image_bytes: bytes) -> bool:
    return len(image_bytes) <= _max_inline_image_size_bytes()


def _pick_smaller(current: bytes, candidate: bytes | None) -> bytes:
    if candidate is not None and len(candidate) < len(current):
        return candidate
    return current


def _resize_image_bytes_if_needed(
    image_bytes: bytes, mime_type: str, *, max_dimension: int = MAX_IMAGE_DIMENSION
) -> bytes:
    media_type = mime_type.lower()
    if not media_type.startswith("image/"):
        return image_bytes

    dims = _detect_image_dimensions(image_bytes, media_type)

    # Downscale if either dimension exceeds the pixel limit
    if dims is not None:
        width, height = dims
        if width > max_dimension or height > max_dimension:
            dim_scale = min(max_dimension / width, max_dimension / height)
            target_width = max(1, int(width * dim_scale))
            target_height = max(1, int(height * dim_scale))
            resized = _resize_image_bytes(image_bytes, media_type, width=target_width, height=target_height)
            if resized is not None:
                image_bytes = resized
                dims = _detect_image_dimensions(image_bytes, media_type)

    if _image_bytes_within_limits(image_bytes):
        return image_bytes

    if dims is None:
        return image_bytes

    current = image_bytes
    width, height = dims
    scale = (_max_inline_image_size_bytes() / len(current)) ** 0.5
    scale *= 0.9

    for _ in range(5):
        target_width = max(1, int(width * scale))
        target_height = max(1, int(height * scale))

        resized = _resize_image_bytes(current, media_type, width=target_width, height=target_height)
        if resized is None:
            return current

        current = resized
        if _image_bytes_within_limits(current):
            return current

        new_dims = _detect_image_dimensions(current, media_type)
        if new_dims is not None:
            width, height = new_dims
        scale = 0.8

    return current


def _compress_image_bytes_for_request(
    image_bytes: bytes,
    mime_type: str,
    *,
    max_dimension: int = MAX_IMAGE_DIMENSION,
) -> tuple[bytes, str]:
    media_type = mime_type.lower()
    if not media_type.startswith("image/"):
        return image_bytes, mime_type

    current = _resize_image_bytes_if_needed(image_bytes, media_type, max_dimension=max_dimension)
    current_mime = media_type

    optimized = _pillow_reencode_image_bytes(current, current_mime)
    current = _pick_smaller(current, optimized)
    if _image_bytes_within_target(current):
        return current, current_mime

    if current_mime == "image/png":
        quantized = _pillow_reencode_image_bytes(current, current_mime, quantize=True)
        current = _pick_smaller(current, quantized)
        if _image_bytes_within_target(current):
            return current, current_mime

    best_jpeg: bytes | None = None
    for quality in _JPEG_FALLBACK_QUALITIES:
        jpeg = _pillow_reencode_image_bytes(current, current_mime, output_mime_type="image/jpeg", quality=quality)
        if jpeg is None:
            continue
        if best_jpeg is None or len(jpeg) < len(best_jpeg):
            best_jpeg = jpeg
        if _image_bytes_within_target(jpeg):
            return jpeg, "image/jpeg"

    if best_jpeg is not None and len(best_jpeg) < len(current):
        return best_jpeg, "image/jpeg"
    return current, current_mime


def parse_data_url(url: str) -> tuple[str, str, bytes]:
    """Parse a base64 data URL and return (mime_type, base64_payload, decoded_bytes)."""

    header_and_media = url.split(",", 1)
    if len(header_and_media) != 2:
        raise ValueError("Invalid data URL for image: missing comma separator")
    header, base64_data = header_and_media
    if not header.startswith("data:"):
        raise ValueError("Invalid data URL for image: missing data: prefix")
    if ";base64" not in header:
        raise ValueError("Invalid data URL for image: missing base64 marker")

    mime_type = header[5:].split(";", 1)[0]
    base64_payload = base64_data.strip()
    if base64_payload == "":
        raise ValueError("Inline image data is empty")

    try:
        decoded = b64decode(base64_payload, validate=True)
    except (BinasciiError, ValueError) as exc:
        raise ValueError("Inline image data is not valid base64") from exc

    return mime_type, base64_payload, decoded


def normalize_image_data_url(url: str, *, max_dimension: int = MAX_IMAGE_DIMENSION) -> str:
    """Normalize a data URL image by resizing oversized inline images and correcting MIME types."""

    if not url.startswith("data:"):
        return url

    mime_type, _, decoded = parse_data_url(url)

    # Correct MIME type if magic bytes disagree with declared type
    detected = detect_mime_type_from_bytes(decoded)
    if detected:
        mime_type = detected

    resized, output_mime_type = _compress_image_bytes_for_request(decoded, mime_type, max_dimension=max_dimension)
    if resized is decoded and output_mime_type == mime_type.lower() and detected is None:
        return url
    encoded = b64encode(resized).decode("ascii")
    return f"data:{output_mime_type};base64,{encoded}"


def freeze_image_for_history(
    image: message.ImageURLPart | message.ImageFilePart,
    *,
    images_dir: Path | None = None,
) -> message.ImageURLPart | message.ImageFilePart:
    """Freeze an image into a stable history representation.

    History images should not be re-encoded on later requests, otherwise prompt
    prefixes can drift between turns. When ``images_dir`` is provided, image
    bytes are snapshotted there and history stores a file reference instead of
    inline base64. Without ``images_dir``, the legacy data URL representation is
    preserved for callers that do not have session storage.
    """

    if images_dir is not None:
        frozen_file = freeze_image_to_file_for_history(image, images_dir=images_dir)
        if frozen_file is not None:
            return frozen_file

    if isinstance(image, message.ImageURLPart):
        url = normalize_image_data_url(image.url) if image.url.startswith("data:") else image.url
        return message.ImageURLPart(
            url=url,
            id=image.id,
            frozen=True,
            source_file_path=image.source_file_path,
        )

    url = image_file_to_data_url(image)
    if url is None:
        return image
    return message.ImageURLPart(url=url, frozen=True, source_file_path=image.file_path)


def freeze_image_to_file_for_history(
    image: message.ImageURLPart | message.ImageFilePart,
    *,
    images_dir: Path,
) -> message.ImageFilePart | None:
    """Snapshot an image into session storage and return a file-backed history part."""

    try:
        if isinstance(image, message.ImageURLPart):
            if not image.url.startswith("data:"):
                return None
            mime_type, _, image_bytes = parse_data_url(normalize_image_data_url(image.url))
        else:
            file_path = Path(image.file_path)
            image_bytes = file_path.read_bytes()
            mime_type = image.mime_type or mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"

        detected = detect_mime_type_from_bytes(image_bytes)
        if detected:
            mime_type = detected
        image_bytes, mime_type = _compress_image_bytes_for_request(image_bytes, mime_type)
        suffix = _suffix_for_mime_type(mime_type) or ".img"
        digest = hashlib.sha256(image_bytes).hexdigest()
        images_dir.mkdir(parents=True, exist_ok=True)
        target = images_dir / f"{digest}{suffix}"
        if not target.exists():
            target.write_bytes(image_bytes)
        return message.ImageFilePart(
            file_path=str(target),
            mime_type=mime_type,
            byte_size=len(image_bytes),
            sha256=digest,
            frozen=True,
        )
    except OSError:
        return None


def _is_session_image_snapshot_path(file_path: Path) -> bool:
    parts = file_path.resolve(strict=False).parts
    for index, part in enumerate(parts):
        if (
            part == ".klaude"
            and index + 5 < len(parts)
            and parts[index + 1] == "projects"
            and parts[index + 3] == "sessions"
            and parts[index + 5] == "images"
        ):
            return True
    return False


def _can_preserve_existing_snapshot(file_path: Path, image_bytes: bytes, mime_type: str, *, max_dimension: int) -> bool:
    if not _is_session_image_snapshot_path(file_path):
        return False
    if not _image_bytes_within_limits(image_bytes):
        return False
    return _image_dimensions_within_limit(image_bytes, mime_type, max_dimension)


def image_url_to_request_url(image: message.ImageURLPart, *, max_dimension: int = MAX_IMAGE_DIMENSION) -> str:
    """Return the URL to send to the model for an ImageURLPart."""

    if image.frozen and (
        not image.url.startswith("data:") or _data_url_within_request_limits(image.url, max_dimension=max_dimension)
    ):
        return image.url
    return normalize_image_data_url(image.url, max_dimension=max_dimension)


def image_file_to_data_url(image: message.ImageFilePart, *, max_dimension: int = MAX_IMAGE_DIMENSION) -> str | None:
    """Load an image file from disk and encode it as a base64 data URL.

    Returns None if the file no longer exists on disk.
    """

    file_path = Path(image.file_path)
    try:
        decoded = file_path.read_bytes()
    except FileNotFoundError:
        return None

    mime_type = image.mime_type
    if not mime_type:
        guessed, _ = mimetypes.guess_type(str(file_path))
        mime_type = guessed or "application/octet-stream"

    # Correct MIME type if magic bytes disagree with extension/metadata
    detected = detect_mime_type_from_bytes(decoded)
    if detected:
        mime_type = detected

    if (
        image.frozen
        and _image_bytes_within_limits(decoded)
        and _image_dimensions_within_limit(decoded, mime_type, max_dimension)
    ):
        encoded = b64encode(decoded).decode("ascii")
        return f"data:{mime_type};base64,{encoded}"

    if not image.frozen and _can_preserve_existing_snapshot(file_path, decoded, mime_type, max_dimension=max_dimension):
        encoded = b64encode(decoded).decode("ascii")
        return f"data:{mime_type};base64,{encoded}"

    decoded, mime_type = _compress_image_bytes_for_request(decoded, mime_type, max_dimension=max_dimension)

    encoded = b64encode(decoded).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"
