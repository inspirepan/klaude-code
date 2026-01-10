from __future__ import annotations

import base64
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import IO

# Kitty graphics protocol chunk size (4096 is the recommended max)
_CHUNK_SIZE = 4096

# Max columns for image display
_MAX_COLS = 80

# Image formats that need conversion to PNG
_NEEDS_CONVERSION = {".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tiff", ".tif"}


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

    try:
        # Convert non-PNG formats to PNG for Kitty graphics protocol compatibility
        if path.suffix.lower() in _NEEDS_CONVERSION:
            data = _convert_to_png(path)
            if data is None:
                print(f"Saved image: {path}", file=file or sys.stdout, flush=True)
                return
        else:
            data = path.read_bytes()

        encoded = base64.standard_b64encode(data).decode("ascii")
        out = file or sys.stdout

        term_size = shutil.get_terminal_size()
        # Only specify columns, let Kitty auto-scale height to preserve aspect ratio
        target_cols = min(_MAX_COLS, term_size.columns)
        size_param = f"c={target_cols}"
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
