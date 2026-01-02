"""Terminal image renderable for Rich console."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from rich.console import ConsoleRenderable, RichCast
from rich.text import Text

if TYPE_CHECKING:
    from rich.console import Console, ConsoleOptions, RenderResult


class TerminalImage(ConsoleRenderable, RichCast):
    """A Rich renderable that displays an image in the terminal using term_image."""

    def __init__(self, file_path: str | Path, height: int | None = None):
        self.file_path = Path(file_path) if isinstance(file_path, str) else file_path
        self.height = height

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        if not self.file_path.exists():
            yield Text(f"Image not found: {self.file_path}")
            return

        try:
            from term_image.image import KittyImage  # type: ignore[import-untyped]

            KittyImage.forced_support = True  # type: ignore[reportUnknownMemberType]
            img = KittyImage.from_file(self.file_path)  # type: ignore[reportUnknownMemberType]
            if self.height is not None:
                img.height = self.height  # type: ignore[reportUnknownMemberType]
            # Write directly to the console's file to bypass Rich's processing
            # which would corrupt Kitty graphics protocol escape sequences
            console.file.write("\x1b[1A\x1b[2K")  # Clear status bar residue from previous line
            console.file.write("\n")
            console.file.write(str(img))
            console.file.write("\n")
            console.file.write("\n")
            console.file.flush()
            # Yield empty text to satisfy the generator requirement
            yield Text("")
        except Exception:
            # Fallback if term_image fails
            yield Text(f"Saved image: {self.file_path}")

    def __rich__(self) -> TerminalImage:
        return self
