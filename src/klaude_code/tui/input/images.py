"""Image handling for REPL input.

This module provides:
- IMAGE_SUFFIXES: Supported image file extensions
- IMAGE_MARKER_RE: Regex for [image ...] markers
- is_image_file(): Check if a path is an image file
- format_image_marker(): Generate [image path] string
- parse_image_marker_path(): Parse path from marker
- capture_clipboard_tag(): Capture clipboard image and return an [image ...] marker
- extract_images_from_text(): Parse [image ...] markers and return ImageURLPart list
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

from klaude_code.const import get_system_temp
from klaude_code.protocol.message import ImageFilePart

# ---------------------------------------------------------------------------
# Constants and marker syntax
# ---------------------------------------------------------------------------

IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".gif", ".webp"})

IMAGE_MARKER_RE = re.compile(r'\[image (?P<path>"[^"]+"|[^\]]+)\]')


def is_image_file(path: Path) -> bool:
    """Check if a path points to an image file based on extension."""
    return path.suffix.lower() in IMAGE_SUFFIXES


def format_image_marker(path: str) -> str:
    """Format a path as an [image ...] marker.

    Paths with whitespace are quoted.
    """
    path_str = path.strip()
    if any(ch.isspace() for ch in path_str):
        return f'[image "{path_str}"]'
    return f"[image {path_str}]"


def parse_image_marker_path(raw: str) -> str:
    """Parse the path from an [image ...] marker, removing quotes if present."""
    s = raw.strip()
    if len(s) >= 2 and s.startswith('"') and s.endswith('"'):
        return s[1:-1]
    return s


# ---------------------------------------------------------------------------
# Clipboard image capture
# ---------------------------------------------------------------------------


def _clipboard_images_dir() -> Path:
    return Path(get_system_temp())


def _grab_clipboard_image_macos(dest_path: Path) -> bool:
    """Grab image from clipboard on macOS using pngpaste or osascript (JXA)."""
    # Try pngpaste first (faster, if installed)
    if shutil.which("pngpaste"):
        try:
            result = subprocess.run(
                ["pngpaste", str(dest_path)],
                capture_output=True,
            )
            return result.returncode == 0 and dest_path.exists() and dest_path.stat().st_size > 0
        except OSError:
            pass

    # Fallback to osascript with JXA (JavaScript for Automation)
    script = f'''
ObjC.import("AppKit");
var pb = $.NSPasteboard.generalPasteboard;
var pngData = pb.dataForType($.NSPasteboardTypePNG);
if (pngData.isNil()) {{
    var tiffData = pb.dataForType($.NSPasteboardTypeTIFF);
    if (tiffData.isNil()) {{
        "false";
    }} else {{
        var bitmapRep = $.NSBitmapImageRep.imageRepWithData(tiffData);
        pngData = bitmapRep.representationUsingTypeProperties($.NSBitmapImageFileTypePNG, $());
    }}
}}
if (!pngData.isNil()) {{
    pngData.writeToFileAtomically("{dest_path}", true);
    "true";
}} else {{
    "false";
}}
'''
    try:
        result = subprocess.run(
            ["osascript", "-l", "JavaScript", "-e", script],
            capture_output=True,
            text=True,
        )
        return (
            result.returncode == 0 and "true" in result.stdout and dest_path.exists() and dest_path.stat().st_size > 0
        )
    except OSError:
        return False


def _grab_clipboard_image_linux(dest_path: Path) -> bool:
    """Grab image from clipboard on Linux using xclip."""
    if not shutil.which("xclip"):
        return False
    try:
        result = subprocess.run(
            ["xclip", "-selection", "clipboard", "-t", "image/png", "-o"],
            capture_output=True,
        )
        if result.returncode == 0 and result.stdout:
            dest_path.write_bytes(result.stdout)
            return True
    except OSError:
        pass
    return False


def _grab_clipboard_image_windows(dest_path: Path) -> bool:
    """Grab image from clipboard on Windows using PowerShell."""
    script = f'''
    Add-Type -AssemblyName System.Windows.Forms
    $img = [System.Windows.Forms.Clipboard]::GetImage()
    if ($img -ne $null) {{
        $img.Save("{dest_path}", [System.Drawing.Imaging.ImageFormat]::Png)
        Write-Output "ok"
    }}
    '''
    try:
        result = subprocess.run(
            ["powershell", "-Command", script],
            capture_output=True,
            text=True,
        )
        return result.returncode == 0 and "ok" in result.stdout and dest_path.exists()
    except OSError:
        return False


def _grab_clipboard_image(dest_path: Path) -> bool:
    """Grab image from clipboard and save to dest_path. Returns True on success."""
    if sys.platform == "darwin":
        return _grab_clipboard_image_macos(dest_path)
    elif sys.platform == "win32":
        return _grab_clipboard_image_windows(dest_path)
    else:
        return _grab_clipboard_image_linux(dest_path)


def capture_clipboard_tag() -> str | None:
    """Capture an image from clipboard and return an [image ...] marker."""

    images_dir = _clipboard_images_dir()
    try:
        images_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None

    filename = f"klaude-image-{uuid.uuid4().hex}.png"
    path = images_dir / filename

    if not _grab_clipboard_image(path):
        return None

    return format_image_marker(str(path))


# ---------------------------------------------------------------------------
# Image extraction from text
# ---------------------------------------------------------------------------


_MIME_TYPES: dict[str, str] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}


def _create_image_file_part(file_path: str) -> ImageFilePart | None:
    """Create an ImageFilePart from a file path."""
    try:
        path = Path(file_path)
        if not path.exists():
            return None

        suffix = path.suffix.lower()
        mime = _MIME_TYPES.get(suffix)
        if mime is None:
            return None

        return ImageFilePart(
            file_path=str(path),
            mime_type=mime,
            byte_size=path.stat().st_size,
        )
    except OSError:
        return None


def extract_images_from_text(text: str) -> list[ImageFilePart]:
    """Extract images referenced by [image ...] markers in text."""

    images: list[ImageFilePart] = []
    for m in IMAGE_MARKER_RE.finditer(text):
        raw = m.group("path")
        path_str = parse_image_marker_path(raw)
        if not path_str:
            continue
        p = Path(path_str).expanduser()
        if not p.is_absolute():
            p = (Path.cwd() / p).resolve()
        image_part = _create_image_file_part(str(p))
        if image_part:
            images.append(image_part)
    return images
