from __future__ import annotations

import base64
import shutil
import struct
import sys
from pathlib import Path
from typing import IO

# Kitty graphics protocol chunk size (4096 is the recommended max)
_CHUNK_SIZE = 4096

# Max columns for non-wide images
_MAX_COLS = 120


def _get_png_dimensions(data: bytes) -> tuple[int, int] | None:
    """Extract width and height from PNG file header."""
    # PNG: 8-byte signature + IHDR chunk (4 len + 4 type + 4 width + 4 height)
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    width, height = struct.unpack(">II", data[16:24])
    return width, height


def print_kitty_image(file_path: str | Path, *, file: IO[str] | None = None) -> None:
    """Print an image to the terminal using Kitty graphics protocol.

    This intentionally bypasses Rich rendering to avoid interleaving Live refreshes
    with raw escape sequences. Image size adapts based on aspect ratio:
    - Landscape images: fill terminal width
    - Portrait images: limit height to avoid oversized display

    Args:
        file_path: Path to the image file (PNG recommended).
        file: Output file stream. Defaults to stdout.
    """
    path = Path(file_path) if isinstance(file_path, str) else file_path
    if not path.exists():
        print(f"Image not found: {path}", file=file or sys.stdout, flush=True)
        return

    try:
        data = path.read_bytes()
        encoded = base64.standard_b64encode(data).decode("ascii")
        out = file or sys.stdout

        term_size = shutil.get_terminal_size()
        dimensions = _get_png_dimensions(data)

        # Determine sizing strategy based on aspect ratio
        if dimensions is not None:
            img_width, img_height = dimensions
            if img_width > 2 * img_height:
                # Wide landscape (width > 2x height): fill terminal width
                size_param = f"c={term_size.columns}"
            else:
                # Other images: limit width to 80% of terminal
                size_param = f"c={min(_MAX_COLS, term_size.columns * 4 // 5)}"
        else:
            # Fallback: limit width to 80% of terminal
            size_param = f"c={min(_MAX_COLS, term_size.columns * 4 // 5)}"
        print("", file=out)
        _write_kitty_graphics(out, encoded, size_param=size_param)
        print("", file=out)
        out.flush()
    except Exception:
        print(f"Saved image: {path}", file=file or sys.stdout, flush=True)


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
            ctrl = f"a=T,f=100,{size_param},m={0 if is_last else 1}"
            out.write(f"\033_G{ctrl};{chunk}\033\\")
        else:
            # Subsequent chunks: only m parameter needed
            out.write(f"\033_Gm={0 if is_last else 1};{chunk}\033\\")
