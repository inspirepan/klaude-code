from __future__ import annotations

import sys
from pathlib import Path
from typing import IO


def print_kitty_image(file_path: str | Path, *, height: int | None = None, file: IO[str] | None = None) -> None:
    """Print an image to the terminal using Kitty graphics protocol.

    This intentionally bypasses Rich rendering to avoid interleaving Live refreshes
    with raw escape sequences.
    """

    path = Path(file_path) if isinstance(file_path, str) else file_path
    if not path.exists():
        print(f"Image not found: {path}", file=file or sys.stdout, flush=True)
        return

    try:
        from term_image.image import KittyImage  # type: ignore[import-untyped]

        KittyImage.forced_support = True  # type: ignore[reportUnknownMemberType]
        img = KittyImage.from_file(path)  # type: ignore[reportUnknownMemberType]
        if height is not None:
            img.height = height  # type: ignore[reportUnknownMemberType]

        out = file or sys.stdout
        print("", file=out)
        print(str(img), file=out)
        print("", file=out)
        out.flush()
    except Exception:
        print(f"Saved image: {path}", file=file or sys.stdout, flush=True)
