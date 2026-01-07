from __future__ import annotations

import base64
import sys
from pathlib import Path
from typing import IO

# Kitty graphics protocol chunk size (4096 is the recommended max)
_CHUNK_SIZE = 4096


def print_kitty_image(file_path: str | Path, *, height: int | None = None, file: IO[str] | None = None) -> None:
    """Print an image to the terminal using Kitty graphics protocol.

    This intentionally bypasses Rich rendering to avoid interleaving Live refreshes
    with raw escape sequences.

    Args:
        file_path: Path to the image file (PNG recommended).
        height: Display height in terminal rows. If None, uses terminal default.
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

        print("", file=out)
        _write_kitty_graphics(out, encoded, height=height)
        print("", file=out)
        out.flush()
    except Exception:
        print(f"Saved image: {path}", file=file or sys.stdout, flush=True)


def _write_kitty_graphics(out: IO[str], encoded_data: str, *, height: int | None = None) -> None:
    """Write Kitty graphics protocol escape sequences.

    Protocol format: ESC _ G <control>;<payload> ESC \\
    - a=T: direct transmission (data in payload)
    - f=100: PNG format (auto-detected by Kitty)
    - r=N: display height in rows
    - m=1: more data follows, m=0: last chunk
    """
    total_len = len(encoded_data)

    for i in range(0, total_len, _CHUNK_SIZE):
        chunk = encoded_data[i : i + _CHUNK_SIZE]
        is_last = i + _CHUNK_SIZE >= total_len

        if i == 0:
            # First chunk: include control parameters
            ctrl = "a=T,f=100"
            if height is not None:
                ctrl += f",r={height}"
            ctrl += f",m={0 if is_last else 1}"
            out.write(f"\033_G{ctrl};{chunk}\033\\")
        else:
            # Subsequent chunks: only m parameter needed
            out.write(f"\033_Gm={0 if is_last else 1};{chunk}\033\\")
