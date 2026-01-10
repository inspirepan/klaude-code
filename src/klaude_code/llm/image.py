"""Image processing utilities for LLM responses.

This module provides reusable image handling primitives that can be shared
across different LLM providers and protocols (OpenAI, Anthropic, etc.).
"""

from __future__ import annotations

import hashlib
import mimetypes
import time
from base64 import b64decode, b64encode
from binascii import Error as BinasciiError
from pathlib import Path

from klaude_code.const import (
    IMAGE_OUTPUT_MAX_BYTES,
    TOOL_OUTPUT_TRUNCATION_DIR,
    ProjectPaths,
    project_key_from_cwd,
)
from klaude_code.protocol import message

IMAGE_EXT_BY_MIME: dict[str, str] = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
}


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


def parse_data_url_image(url: str) -> tuple[str, bytes]:
    """Parse a base64 data URL and return (mime_type, decoded_bytes)."""

    mime_type, _, decoded = parse_data_url(url)
    return mime_type, decoded


def get_assistant_image_output_dir(session_id: str | None) -> Path:
    """Get the output directory for assistant-generated images."""
    if session_id:
        paths = ProjectPaths(project_key=project_key_from_cwd())
        return paths.images_dir(session_id)
    return Path(TOOL_OUTPUT_TRUNCATION_DIR) / "images"


def save_assistant_image(
    *, data_url: str, session_id: str | None, response_id: str | None, image_index: int
) -> message.ImageFilePart:
    """Decode a data URL image and save it to the session image artifacts directory."""

    mime_type, decoded = parse_data_url_image(data_url)

    if len(decoded) > IMAGE_OUTPUT_MAX_BYTES:
        decoded_mb = len(decoded) / (1024 * 1024)
        limit_mb = IMAGE_OUTPUT_MAX_BYTES / (1024 * 1024)
        raise ValueError(f"Image output size ({decoded_mb:.2f}MB) exceeds limit ({limit_mb:.2f}MB)")

    output_dir = get_assistant_image_output_dir(session_id)
    output_dir.mkdir(parents=True, exist_ok=True)

    ext = IMAGE_EXT_BY_MIME.get(mime_type, ".bin")
    response_part = (response_id or "unknown").replace("/", "_")
    ts = time.time_ns()
    file_path = output_dir / f"img-{response_part}-{image_index}-{ts}{ext}"
    file_path.write_bytes(decoded)

    return message.ImageFilePart(
        file_path=str(file_path),
        mime_type=mime_type,
        byte_size=len(decoded),
        sha256=hashlib.sha256(decoded).hexdigest(),
    )


def image_file_to_data_url(image: message.ImageFilePart) -> str:
    """Load an image file from disk and encode it as a base64 data URL."""

    file_path = Path(image.file_path)
    decoded = file_path.read_bytes()

    mime_type = image.mime_type
    if not mime_type:
        guessed, _ = mimetypes.guess_type(str(file_path))
        mime_type = guessed or "application/octet-stream"

    encoded = b64encode(decoded).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def assistant_image_to_data_url(image: message.ImageFilePart) -> str:
    """Load an assistant image from disk and encode it as a base64 data URL.

    This is primarily used for multi-turn image editing, where providers require
    sending the previous assistant message (including images) back to the model.
    """

    file_path = Path(image.file_path)
    if file_path.stat().st_size > IMAGE_OUTPUT_MAX_BYTES:
        size_mb = file_path.stat().st_size / (1024 * 1024)
        limit_mb = IMAGE_OUTPUT_MAX_BYTES / (1024 * 1024)
        raise ValueError(f"Assistant image size ({size_mb:.2f}MB) exceeds limit ({limit_mb:.2f}MB)")

    return image_file_to_data_url(image)
