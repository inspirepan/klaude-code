"""Clipboard and image handling for REPL input.

This module provides:
- ClipboardCaptureState: Captures clipboard images and maps tags to file paths
- capture_clipboard_tag(): Capture clipboard image and return tag
- extract_images_from_text(): Parse tags and return ImageURLPart list
- copy_to_clipboard(): Copy text to system clipboard
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import uuid
from base64 import b64encode
from pathlib import Path

from klaude_code.protocol.message import ImageURLPart

# Directory for storing clipboard images
CLIPBOARD_IMAGES_DIR = Path.home() / ".klaude" / "clipboard" / "images"

# Pattern to match [Image #N] tags in user input
_IMAGE_TAG_RE = re.compile(r"\[Image #(\d+)\]")


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
        return result.returncode == 0 and "true" in result.stdout and dest_path.exists() and dest_path.stat().st_size > 0
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


class ClipboardCaptureState:
    """Captures clipboard images and maps tags to file paths in memory."""

    def __init__(self, images_dir: Path | None = None):
        self._images_dir = images_dir or CLIPBOARD_IMAGES_DIR
        self._pending: dict[str, str] = {}  # tag -> path mapping
        self._counter = 1

    def capture_from_clipboard(self) -> str | None:
        """Capture image from clipboard, save to disk, and return a tag like [Image #N]."""
        try:
            self._images_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            return None

        filename = f"clipboard_{uuid.uuid4().hex[:8]}.png"
        path = self._images_dir / filename

        if not _grab_clipboard_image(path):
            return None

        tag = f"[Image #{self._counter}]"
        self._counter += 1
        self._pending[tag] = str(path)
        return tag

    def get_pending_images(self) -> dict[str, str]:
        """Return the current tag-to-path mapping for pending images."""
        return dict(self._pending)

    def flush(self) -> dict[str, str]:
        """Flush pending images and return tag-to-path mapping, then reset state."""
        result = dict(self._pending)
        self._pending = {}
        self._counter = 1
        return result


# Module-level singleton instance
clipboard_state = ClipboardCaptureState()


def capture_clipboard_tag() -> str | None:
    """Capture image from clipboard and return tag like [Image #N].

    Uses the module-level clipboard_state singleton. Returns None if no image
    is available in the clipboard or capture fails.
    """
    return clipboard_state.capture_from_clipboard()


def extract_images_from_text(text: str) -> list[ImageURLPart]:
    """Extract images from pending clipboard state based on tags in text.

    Parses [Image #N] tags in the text, looks up corresponding image paths
    in the clipboard state, and creates ImageURLPart objects from them.
    Flushes the clipboard state after extraction.
    """
    pending_images = clipboard_state.flush()
    if not pending_images:
        return []

    # Find all [Image #N] tags in text
    found_tags = set(_IMAGE_TAG_RE.findall(text))
    if not found_tags:
        return []

    images: list[ImageURLPart] = []
    for tag, path in pending_images.items():
        # Extract the number from the tag and check if it's referenced
        match = _IMAGE_TAG_RE.match(tag)
        if match and match.group(1) in found_tags:
            image_part = _encode_image_file(path)
            if image_part:
                images.append(image_part)

    return images


def _encode_image_file(file_path: str) -> ImageURLPart | None:
    """Encode an image file as base64 data URL and create ImageURLPart."""
    try:
        path = Path(file_path)
        if not path.exists():
            return None
        with open(path, "rb") as f:
            encoded = b64encode(f.read()).decode("ascii")
        # Clipboard images are always saved as PNG
        data_url = f"data:image/png;base64,{encoded}"
        return ImageURLPart(url=data_url, id=None)
    except OSError:
        return None


def copy_to_clipboard(text: str) -> None:
    """Copy text to system clipboard using platform-specific commands."""
    try:
        if sys.platform == "darwin":
            subprocess.run(["pbcopy"], input=text.encode("utf-8"), check=True)
        elif sys.platform == "win32":
            subprocess.run(["clip"], input=text.encode("utf-16"), check=True)
        else:
            # Linux: try xclip first, then xsel
            if shutil.which("xclip"):
                subprocess.run(
                    ["xclip", "-selection", "clipboard"],
                    input=text.encode("utf-8"),
                    check=True,
                )
            elif shutil.which("xsel"):
                subprocess.run(
                    ["xsel", "--clipboard", "--input"],
                    input=text.encode("utf-8"),
                    check=True,
                )
    except (OSError, subprocess.SubprocessError):
        pass
