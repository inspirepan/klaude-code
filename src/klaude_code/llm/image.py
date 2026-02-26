"""Image processing utilities for LLM responses.

This module provides reusable image handling primitives that can be shared
across different LLM providers and protocols (OpenAI, Anthropic, etc.).
"""

from __future__ import annotations

import mimetypes
from base64 import b64decode, b64encode
from binascii import Error as BinasciiError
from pathlib import Path

from klaude_code.const import (
    TOOL_OUTPUT_TRUNCATION_DIR,
    ProjectPaths,
    project_key_from_cwd,
)
from klaude_code.protocol import message


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
