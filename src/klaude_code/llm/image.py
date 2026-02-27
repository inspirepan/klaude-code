"""Image processing utilities for LLM responses.

This module provides reusable image handling primitives that can be shared
across different LLM providers and protocols (OpenAI, Anthropic, etc.).
"""

from __future__ import annotations

import mimetypes
import shutil
import subprocess
import sys
import tempfile
from base64 import b64decode, b64encode
from binascii import Error as BinasciiError
from pathlib import Path

from klaude_code.const import (
    TOOL_OUTPUT_TRUNCATION_DIR,
    ProjectPaths,
    project_key_from_cwd,
)
from klaude_code.protocol import message

_MAX_IMAGE_SIZE_BYTES = 4_500_000
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


def _resize_image_bytes(image_bytes: bytes, mime_type: str, *, width: int, height: int) -> bytes | None:
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


def _resize_image_bytes_if_needed(image_bytes: bytes, mime_type: str) -> bytes:
    if len(image_bytes) <= _MAX_IMAGE_SIZE_BYTES:
        return image_bytes

    media_type = mime_type.lower()
    if not media_type.startswith("image/"):
        return image_bytes

    dims = _detect_image_dimensions(image_bytes, media_type)
    if dims is None:
        return image_bytes

    current = image_bytes
    width, height = dims
    scale = (_MAX_IMAGE_SIZE_BYTES / len(current)) ** 0.5
    scale *= 0.9

    for _ in range(5):
        target_width = max(1, int(width * scale))
        target_height = max(1, int(height * scale))

        resized = _resize_image_bytes(current, media_type, width=target_width, height=target_height)
        if resized is None:
            return current

        current = resized
        if len(current) <= _MAX_IMAGE_SIZE_BYTES:
            return current

        new_dims = _detect_image_dimensions(current, media_type)
        if new_dims is not None:
            width, height = new_dims
        scale = 0.8

    return current


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


def get_assistant_image_output_dir(session_id: str | None) -> Path:
    """Get the output directory for assistant-generated images."""
    if session_id:
        paths = ProjectPaths(project_key=project_key_from_cwd())
        return paths.images_dir(session_id)
    return Path(TOOL_OUTPUT_TRUNCATION_DIR) / "images"


def normalize_image_data_url(url: str) -> str:
    """Normalize a data URL image by resizing oversized images to 4.5MB."""

    if not url.startswith("data:"):
        return url

    mime_type, _, decoded = parse_data_url(url)
    resized = _resize_image_bytes_if_needed(decoded, mime_type)
    if resized == decoded:
        return url
    encoded = b64encode(resized).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def image_file_to_data_url(image: message.ImageFilePart) -> str:
    """Load an image file from disk and encode it as a base64 data URL."""

    file_path = Path(image.file_path)
    decoded = file_path.read_bytes()

    mime_type = image.mime_type
    if not mime_type:
        guessed, _ = mimetypes.guess_type(str(file_path))
        mime_type = guessed or "application/octet-stream"

    decoded = _resize_image_bytes_if_needed(decoded, mime_type)

    encoded = b64encode(decoded).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"
