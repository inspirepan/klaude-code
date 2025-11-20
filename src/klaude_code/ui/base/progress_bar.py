"""
Use OSC 9;4;... to control progress bar in terminal like Ghostty
States:
  0/hidden
  1/normal
  2/error
  3/indeterminate
  4/warning
"""

import os
import sys
import time
from enum import Enum
from typing import TextIO, cast

is_ghostty = os.environ.get("TERM") == "xterm-ghostty" or "GHOSTTY_RESOURCES_DIR" in os.environ

ST = "\033\\"  # ESC \
BEL = "\a"  # Some terminals also accept BEL as terminator


class OSC94States(Enum):
    HIDDEN = 0
    NORMAL = 1
    ERROR = 2
    INDETERMINATE = 3
    WARNING = 4


def resolve_stream(stream: TextIO | None) -> TextIO:
    """
    Rich's status.start() (backed by Live) temporarily replaces sys.stdout/sys.stderr with a
    Console._redirect_stdio wrapper. The wrapper strips control codes like OSC and BEL before
    writing, so sequences such as \\x1b]9;4;3\\x1b\\ are truncated to ]9;4;3. Using sys.__stdout__ or
    an explicit Console file handle bypasses the wrapper and preserves the full OSC payload.
    """
    if stream is not None:
        return stream
    if hasattr(sys, "__stdout__") and sys.__stdout__ is not None:
        return cast(TextIO, sys.__stdout__)
    return sys.stdout


def emit_osc94(
    state: OSC94States,
    progress: int | None = None,
    *,
    use_bel: bool = False,
    stream: TextIO | None = None,
):
    if not is_ghostty:
        return

    seq = f"\033]9;4;{state.value}"
    if state == OSC94States.NORMAL:  # Normal progress needs percentage
        if progress is None:
            progress = 0
        seq += f";{int(progress)}"
    terminator = BEL if use_bel else ST
    output = resolve_stream(stream)
    output.write(seq + terminator)
    output.flush()


if __name__ == "__main__":
    for i in range(101):
        emit_osc94(OSC94States.NORMAL, i)
        time.sleep(0.02)

    # Clear progress bar
    emit_osc94(OSC94States.HIDDEN)

    print("Waiting...")
    # Indeterminate
    emit_osc94(OSC94States.INDETERMINATE)

    time.sleep(2)
    print("Error...")
    # Error
    emit_osc94(OSC94States.ERROR)

    time.sleep(2)
    print("Warning...")
    # Warning
    emit_osc94(OSC94States.WARNING)
    time.sleep(2)
