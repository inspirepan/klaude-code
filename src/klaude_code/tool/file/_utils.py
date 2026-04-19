"""Shared utility functions for file tools."""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path


def is_directory(path: str) -> bool:
    """Check if path is a directory."""
    return os.path.isdir(path)

def file_exists(path: str) -> bool:
    """Check if path exists."""
    return os.path.exists(path)

def detect_encoding(path: str) -> str:
    """Detect file encoding by checking for UTF-16LE BOM."""
    try:
        with open(path, "rb") as f:
            bom = f.read(2)
            if len(bom) >= 2 and bom[0] == 0xFF and bom[1] == 0xFE:
                return "utf-16-le"
    except OSError:
        pass
    return "utf-8"

def read_text(path: str) -> str:
    """Read text from file with automatic encoding detection."""
    encoding = detect_encoding(path)
    with open(path, encoding=encoding, errors="replace") as f:
        content = f.read()
    # Normalize CRLF to LF
    return content.replace("\r\n", "\n")

def read_text_with_encoding(path: str) -> tuple[str, str]:
    """Read text from file, returning (content, encoding)."""
    encoding = detect_encoding(path)
    with open(path, encoding=encoding, errors="replace") as f:
        content = f.read()
    return content.replace("\r\n", "\n"), encoding

def write_text(path: str, content: str, encoding: str = "utf-8") -> None:
    """Write text to file, creating parent directories if needed.

    For UTF-16LE files, a BOM (FF FE) is prepended so the file remains
    detectable as UTF-16LE on subsequent reads.
    """
    parent = Path(path).parent
    parent.mkdir(parents=True, exist_ok=True)
    if encoding == "utf-16-le":
        with open(path, "wb") as f:
            f.write(b"\xff\xfe")
            f.write(content.encode("utf-16-le"))
    else:
        with open(path, "w", encoding=encoding) as f:
            f.write(content)

def hash_text_sha256(content: str) -> str:
    """Return SHA-256 for the given text content encoded as UTF-8."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()

def is_blocked_device_path(file_path: str) -> bool:
    """Check if file_path is a device path that would hang the process."""
    from klaude_code.const import BLOCKED_DEVICE_PATHS

    if file_path in BLOCKED_DEVICE_PATHS:
        return True
    # /proc/self/fd/0-2 and /proc/<pid>/fd/0-2 are Linux aliases for stdio
    return file_path.startswith("/proc/") and (
        file_path.endswith("/fd/0") or file_path.endswith("/fd/1") or file_path.endswith("/fd/2")
    )

# -- Quote normalization utilities (curly quotes <-> straight quotes) --

LEFT_SINGLE_CURLY = "\u2018"  # '
RIGHT_SINGLE_CURLY = "\u2019"  # '
LEFT_DOUBLE_CURLY = "\u201c"  # "
RIGHT_DOUBLE_CURLY = "\u201d"  # "

def normalize_quotes(s: str) -> str:
    """Convert curly quotes to straight quotes."""
    return (
        s.replace(LEFT_SINGLE_CURLY, "'")
        .replace(RIGHT_SINGLE_CURLY, "'")
        .replace(LEFT_DOUBLE_CURLY, '"')
        .replace(RIGHT_DOUBLE_CURLY, '"')
    )

def find_actual_string(file_content: str, search_string: str) -> str | None:
    """Find the actual string in file content, accounting for quote normalization.

    Returns the actual string found in the file, or None if not found.
    """
    if search_string in file_content:
        return search_string

    normalized_search = normalize_quotes(search_string)
    normalized_file = normalize_quotes(file_content)
    idx = normalized_file.find(normalized_search)
    if idx != -1:
        return file_content[idx : idx + len(search_string)]
    return None

def _is_opening_context(chars: list[str], index: int) -> bool:
    if index == 0:
        return True
    prev = chars[index - 1]
    return prev in {" ", "\t", "\n", "\r", "(", "[", "{", "\u2014", "\u2013"}

def _apply_curly_double_quotes(s: str) -> str:
    chars = list(s)
    result: list[str] = []
    for i, ch in enumerate(chars):
        if ch == '"':
            result.append(LEFT_DOUBLE_CURLY if _is_opening_context(chars, i) else RIGHT_DOUBLE_CURLY)
        else:
            result.append(ch)
    return "".join(result)

def _apply_curly_single_quotes(s: str) -> str:
    chars = list(s)
    result: list[str] = []
    letter_re = re.compile(r"\w", re.UNICODE)
    for i, ch in enumerate(chars):
        if ch == "'":
            prev = chars[i - 1] if i > 0 else ""
            nxt = chars[i + 1] if i < len(chars) - 1 else ""
            if letter_re.match(prev) and letter_re.match(nxt):
                result.append(RIGHT_SINGLE_CURLY)
            else:
                result.append(LEFT_SINGLE_CURLY if _is_opening_context(chars, i) else RIGHT_SINGLE_CURLY)
        else:
            result.append(ch)
    return "".join(result)

def preserve_quote_style(old_string: str, actual_old_string: str, new_string: str) -> str:
    """When old_string matched via quote normalization, apply the same curly style to new_string."""
    if old_string == actual_old_string:
        return new_string

    has_double = LEFT_DOUBLE_CURLY in actual_old_string or RIGHT_DOUBLE_CURLY in actual_old_string
    has_single = LEFT_SINGLE_CURLY in actual_old_string or RIGHT_SINGLE_CURLY in actual_old_string

    if not has_double and not has_single:
        return new_string

    result = new_string
    if has_double:
        result = _apply_curly_double_quotes(result)
    if has_single:
        result = _apply_curly_single_quotes(result)
    return result

def strip_trailing_whitespace(s: str) -> str:
    """Strip trailing whitespace from each line, preserving line endings."""
    lines = s.split("\n")
    return "\n".join(line.rstrip() for line in lines)
