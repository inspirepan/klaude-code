from __future__ import annotations

import base64
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import IO

from klaude_code.tui.terminal import supports_kitty_graphics

# Kitty graphics protocol chunk size (4096 is the recommended max)
_CHUNK_SIZE = 4096

# Max columns for image display
_MAX_COLS = 100

# Max rows for image display
_MAX_ROWS = 35

# Minimum visible width (in terminal columns) for very tall diagrams.
_MIN_READABLE_COLS = 50

# Upper bound for row expansion when preserving readability of tall diagrams.
_MAX_TALL_ROWS = 120

# Image formats that need conversion to PNG
_NEEDS_CONVERSION = {".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tiff", ".tif"}

# Approximate pixels per terminal cell (typical for most terminals)
_PIXELS_PER_COL = 9
_PIXELS_PER_ROW = 18


def _get_png_dimensions(data: bytes) -> tuple[int, int] | None:
    """Extract width and height from PNG header (IHDR chunk)."""
    # PNG signature (8 bytes) + IHDR length (4 bytes) + "IHDR" (4 bytes) + width (4 bytes) + height (4 bytes)
    if len(data) < 28 or data[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    width = int.from_bytes(data[16:20], "big")
    height = int.from_bytes(data[20:24], "big")
    return width, height


def _convert_to_png(path: Path) -> bytes | None:
    """Convert image to PNG using sips (macOS) or convert (ImageMagick)."""
    with tempfile.NamedTemporaryFile(suffix=".png", delete=True) as tmp:
        tmp_path = tmp.name
        # Try sips first (macOS built-in)
        result = subprocess.run(
            ["sips", "-s", "format", "png", str(path), "--out", tmp_path],
            capture_output=True,
        )
        if result.returncode == 0:
            return Path(tmp_path).read_bytes()
        # Fallback to ImageMagick convert
        result = subprocess.run(
            ["convert", str(path), tmp_path],
            capture_output=True,
        )
        if result.returncode == 0:
            return Path(tmp_path).read_bytes()
    return None


def print_kitty_image(file_path: str | Path, *, file: IO[str] | None = None) -> None:
    """Print an image to the terminal using Kitty graphics protocol.

    Only specifies column width; Kitty auto-scales height to preserve aspect ratio.
    """
    path = Path(file_path) if isinstance(file_path, str) else file_path
    if not path.exists():
        print(f"Image not found: {path}", file=file or sys.stdout, flush=True)
        return

    if not supports_kitty_graphics():
        print(f"[[Image: {path}]]", file=file or sys.stdout, flush=True)
        return

    try:
        source_data = path.read_bytes()

        # Some producers may write PNG bytes with a non-PNG extension (e.g. .svg).
        # If the file is already PNG, render it directly without conversion.
        if _get_png_dimensions(source_data) is not None:
            data = source_data
        elif path.suffix.lower() == ".svg":
            print(f"[[Image: {path}]]", file=file or sys.stdout, flush=True)
            return
        elif path.suffix.lower() in _NEEDS_CONVERSION:
            data = _convert_to_png(path)
            if data is None:
                print(f"[[Image: {path}]]", file=file or sys.stdout, flush=True)
                return
        else:
            data = source_data

        out = file or sys.stdout

        term_size = shutil.get_terminal_size()
        target_cols = min(_MAX_COLS, term_size.columns)

        size_param = ""
        dimensions = _get_png_dimensions(data)
        if dimensions is not None:
            img_width, img_height = dimensions
            img_cols = max(img_width // _PIXELS_PER_COL, 1)
            img_rows = max(img_height // _PIXELS_PER_ROW, 1)
            exceeds_width = img_cols > target_cols
            exceeds_height = img_rows > _MAX_ROWS
            if exceeds_width and exceeds_height:
                # Both exceed: use the more constrained dimension to preserve aspect ratio
                width_scale = target_cols / img_cols
                height_scale = _MAX_ROWS / img_rows
                size_param = f"c={target_cols}" if width_scale < height_scale else f"r={_MAX_ROWS}"
            elif exceeds_width:
                size_param = f"c={target_cols}"
            elif exceeds_height:
                size_param = "" if img_rows <= _MAX_TALL_ROWS else f"r={_MAX_ROWS}"

            if not size_param and exceeds_height and img_cols < _MIN_READABLE_COLS:
                readable_cols = min(_MIN_READABLE_COLS, target_cols)
                rows_if_readable = (img_rows * readable_cols + img_cols - 1) // img_cols
                if rows_if_readable <= _MAX_TALL_ROWS:
                    size_param = f"c={readable_cols}"

            if size_param.startswith("r="):
                constrained_rows = int(size_param[2:])
                constrained_cols = img_cols * constrained_rows / img_rows
                if constrained_cols < _MIN_READABLE_COLS:
                    required_rows = (_MIN_READABLE_COLS * img_rows + img_cols - 1) // img_cols
                    boosted_rows = min(max(constrained_rows, required_rows), _MAX_TALL_ROWS)
                    if exceeds_width:
                        rows_if_width_constrained = (img_rows * target_cols + img_cols - 1) // img_cols
                        if rows_if_width_constrained <= _MAX_TALL_ROWS:
                            size_param = f"c={target_cols}"
                        else:
                            size_param = f"r={boosted_rows}"
                    elif img_rows <= boosted_rows:
                        size_param = ""
                    else:
                        size_param = f"r={boosted_rows}"
        else:
            # Fallback: constrain by height since we can't determine image size
            size_param = f"r={_MAX_ROWS}"
        print("", file=out)
        if not _write_kitty_graphics_via_file(out, data, size_param=size_param):
            encoded = base64.standard_b64encode(data).decode("ascii")
            _write_kitty_graphics(out, encoded, size_param=size_param)
        print("", file=out)
        out.flush()
    except Exception:
        print(f"[[Image: {path}]]", file=file or sys.stdout, flush=True)


def _supports_kitty_file_transmission() -> bool:
    """Whether the terminal can read image files from disk (kitty t=t medium).

    Only kitty and Ghostty implement the file-based transmission mediums
    reliably; WezTerm/Konsole advertise the graphics protocol but their
    support is partial. Over SSH the terminal runs on another host and
    cannot see local files, so inline transmission is required.
    """
    if os.environ.get("SSH_TTY") or os.environ.get("SSH_CONNECTION"):
        return False
    term_program = os.environ.get("TERM_PROGRAM", "").lower()
    term = os.environ.get("TERM", "").lower()
    return any(name in term_program or name in term for name in ("kitty", "ghostty"))


# Keep t=f snapshot files around long enough for the terminal to read them
# asynchronously; prune anything older on the next image render.
_KITTY_FILE_MAX_AGE_S = 3600.0
_KITTY_FILE_PREFIX = "klaude-kitty-"


def _prune_stale_kitty_files(tmp_dir: Path) -> None:
    import time

    cutoff = time.time() - _KITTY_FILE_MAX_AGE_S
    try:
        for stale in tmp_dir.glob(f"{_KITTY_FILE_PREFIX}*.png"):
            try:
                if stale.stat().st_mtime < cutoff:
                    stale.unlink()
            except OSError:
                continue
    except OSError:
        pass


def _write_kitty_graphics_via_file(out: IO[str], data: bytes, *, size_param: str) -> bool:
    """Transmit an image by file path (kitty t=f medium) instead of inline base64.

    An inline payload is megabytes of base64 in a single escape sequence; the
    scrollback write cycle keeps the bottom UI erased until a slow terminal
    drains all of it. With file transmission the payload is just the encoded
    path (~100 bytes) and the terminal reads the image from disk itself.

    Uses t=f rather than t=t: t=t asks the terminal to delete the file after
    reading, but Ghostty deletes before its async decode completes and the
    image never shows. We keep ownership of the temp files and prune old
    ones ourselves.
    """
    if not _supports_kitty_file_transmission():
        return False
    try:
        # /tmp keeps paths short and world-readable for the terminal process;
        # fall back to the platform default when it doesn't exist.
        tmp_dir = Path("/tmp") if os.path.isdir("/tmp") else Path(tempfile.gettempdir())
        _prune_stale_kitty_files(tmp_dir)
        fd, tmp_path = tempfile.mkstemp(prefix=_KITTY_FILE_PREFIX, suffix=".png", dir=str(tmp_dir))
        with os.fdopen(fd, "wb") as tmp_file:
            tmp_file.write(data)
    except OSError:
        return False
    encoded_path = base64.standard_b64encode(tmp_path.encode("utf-8")).decode("ascii")
    base_ctrl = f"a=T,f=100,t=f,{size_param}" if size_param else "a=T,f=100,t=f"
    out.write(f"\033_G{base_ctrl};{encoded_path}\033\\")
    return True


def _write_kitty_graphics(out: IO[str], encoded_data: str, *, size_param: str) -> None:
    """Write Kitty graphics protocol escape sequences.

    Protocol format: ESC _ G <control>;<payload> ESC \\
    - a=T: direct transmission (data in payload)
    - f=100: PNG format (auto-detected by Kitty)
    - c=N: display width in columns
    - r=N: display height in rows
    - m=1: more data follows, m=0: last chunk
    """
    total_len = len(encoded_data)

    for i in range(0, total_len, _CHUNK_SIZE):
        chunk = encoded_data[i : i + _CHUNK_SIZE]
        is_last = i + _CHUNK_SIZE >= total_len

        if i == 0:
            # First chunk: include control parameters
            base_ctrl = f"a=T,f=100,{size_param}" if size_param else "a=T,f=100"
            ctrl = f"{base_ctrl},m={0 if is_last else 1}"
            out.write(f"\033_G{ctrl};{chunk}\033\\")
        else:
            # Subsequent chunks: only m parameter needed
            out.write(f"\033_Gm={0 if is_last else 1};{chunk}\033\\")
