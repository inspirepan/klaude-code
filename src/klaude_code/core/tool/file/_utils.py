"""Shared utility functions for file tools."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path


def is_directory(path: str) -> bool:
    """Check if path is a directory."""
    return os.path.isdir(path)


def file_exists(path: str) -> bool:
    """Check if path exists."""
    return os.path.exists(path)


def read_text(path: str) -> str:
    """Read text from file with UTF-8 encoding."""
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read()


def write_text(path: str, content: str) -> None:
    """Write text to file, creating parent directories if needed."""
    parent = Path(path).parent
    parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def hash_text_sha256(content: str) -> str:
    """Return SHA-256 for the given text content encoded as UTF-8."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()
