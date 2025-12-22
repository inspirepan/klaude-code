from __future__ import annotations

import os
import re
import select
import sys
import termios
import time
import tty
from typing import BinaryIO, Final

from klaude_code.trace import DebugType, log_debug

ST: Final[bytes] = b"\x1b\\"  # ESC \
BEL: Final[int] = 7

# Match OSC 11 response like: ESC ] 11 ; <payload> BEL/ST
_OSC_BG_REGEX = re.compile(r"\x1b]11;([^\x07\x1b\\]*)")

# Cache for the last successfully detected terminal background RGB.
_last_bg_rgb: tuple[int, int, int] | None = None


def is_light_terminal_background(timeout: float = 0.5) -> bool | None:
    """Detect whether the current terminal background is light.

    Returns True for light background, False for dark, and None if detection fails.
    """

    rgb = _query_color_slot(slot=11, timeout=timeout)
    if rgb is None:
        return None

    global _last_bg_rgb
    _last_bg_rgb = rgb

    r, g, b = rgb
    # Same luminance formula as codex-rs: 0.299*r + 0.587*g + 0.114*b > 128.0
    y = 0.299 * float(r) + 0.587 * float(g) + 0.114 * float(b)
    return y > 128.0


def get_last_terminal_background_rgb() -> tuple[int, int, int] | None:
    """Return the last detected terminal background RGB, if available.

    The value is populated as a side effect of ``is_light_terminal_background``
    (which queries OSC 11). If detection has not run or failed, this returns
    None.
    """

    return _last_bg_rgb


def _query_color_slot(slot: int, timeout: float) -> tuple[int, int, int] | None:
    """Query an OSC color slot (10=fg, 11=bg) and return RGB if possible.

    This sends OSC `ESC ] slot ; ? ESC \\` to the controlling TTY and then
    reads back the response directly from `/dev/tty`, consuming the bytes so
    they do not leak into the next shell prompt.
    """

    if sys.platform == "win32":
        return None

    term = os.getenv("TERM", "").lower()
    if term in {"", "dumb"}:
        return None

    try:
        with open("/dev/tty", "r+b", buffering=0) as tty_fp:
            fd = tty_fp.fileno()
            if not os.isatty(fd):
                return None

            try:
                old_attrs = termios.tcgetattr(fd)
            except Exception as exc:  # termios.error and others
                log_debug(
                    f"Failed to get termios attributes for /dev/tty: {exc}",
                    debug_type=DebugType.TERMINAL,
                )
                old_attrs = None

            try:
                if old_attrs is not None:
                    # Put tty into cbreak mode so we can read the OSC response bytes immediately.
                    tty.setcbreak(fd)

                _send_osc_query(tty_fp, slot)
                raw = _read_osc_response(fd, timeout=timeout)
            finally:
                if old_attrs is not None:
                    try:
                        termios.tcsetattr(fd, termios.TCSADRAIN, old_attrs)
                    except Exception as exc:  # best-effort restore
                        log_debug(
                            f"Failed to restore termios attributes for /dev/tty: {exc}",
                            debug_type=DebugType.TERMINAL,
                        )

    except OSError as exc:
        log_debug(
            f"Failed to open /dev/tty for OSC color query: {exc}",
            debug_type=DebugType.TERMINAL,
        )
        return None

    if raw is None or not raw:
        return None

    return _parse_osc_color_response(raw)


def _send_osc_query(tty_fp: BinaryIO, slot: int) -> None:
    """Send OSC color query for the given slot to the TTY."""

    seq = f"\x1b]{slot};?\x1b\\".encode("ascii", errors="ignore")
    try:
        tty_fp.write(seq)
        tty_fp.flush()
    except Exception as exc:
        log_debug(
            f"Failed to write OSC color query to /dev/tty: {exc}",
            debug_type=DebugType.TERMINAL,
        )


def _read_osc_response(fd: int, timeout: float) -> bytes | None:
    """Read a single OSC response terminated by BEL or ST from the TTY.

    The bytes are consumed from `/dev/tty` so that the terminal's reply does
    not become visible as part of the next shell prompt.
    """

    deadline = time.monotonic() + max(timeout, 0.0)
    buf = bytearray()

    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break

        readable, _, _ = select.select([fd], [], [], remaining)
        if not readable:
            continue

        try:
            chunk = os.read(fd, 1024)
        except Exception as exc:
            log_debug(
                f"Failed to read OSC color response from /dev/tty: {exc}",
                debug_type=DebugType.TERMINAL,
            )
            break

        if not chunk:
            break

        buf.extend(chunk)

        # BEL terminator
        if BEL in buf:
            idx = buf.index(BEL)
            return bytes(buf[: idx + 1])

        # ST terminator (ESC \), may span chunks so search the whole buffer
        st_index = buf.find(ST)
        if st_index != -1:
            return bytes(buf[: st_index + len(ST)])

    if buf:
        return bytes(buf)
    return None


def _parse_osc_color_response(data: bytes) -> tuple[int, int, int] | None:
    """Extract an RGB triple from an OSC 11 response payload.

    Supports typical xterm-style responses like `ESC ] 11 ; rgb:rrrr/gggg/bbbb BEL` or
    `ESC ] 11 ; #rrggbb BEL`.
    """

    try:
        text = data.decode("ascii", errors="ignore")
    except LookupError:  # encoding lookup failure (should not happen with "ascii")
        return None

    match = _OSC_BG_REGEX.search(text)
    if not match:
        return None

    payload = match.group(1).strip()
    # In case the terminal adds extra metadata separated by ';', only use the first field.
    payload = payload.split(";", 1)[0].strip()

    rgb = _parse_rgb_spec(payload)
    return rgb


def _parse_rgb_spec(spec: str) -> tuple[int, int, int] | None:
    """Parse a color specification like `rgb:rrrr/gggg/bbbb` or `#rrggbb`."""

    spec = spec.strip()

    # xterm-style rgb:rrrr/gggg/bbbb where each component is 1-4 hex digits
    if spec.lower().startswith("rgb:"):
        body = spec[4:]
        parts = body.split("/")
        if len(parts) != 3:
            return None
        try:
            r = _scale_hex_component(parts[0])
            g = _scale_hex_component(parts[1])
            b = _scale_hex_component(parts[2])
        except ValueError:
            return None
        return r, g, b

    # Simple #rrggbb response
    if spec.startswith("#") and len(spec) == 7:
        try:
            r = int(spec[1:3], 16)
            g = int(spec[3:5], 16)
            b = int(spec[5:7], 16)
        except ValueError:
            return None
        return r, g, b

    return None


def _scale_hex_component(component: str) -> int:
    """Scale 1-4 digit hex component to 0-255 range."""

    if not component:
        raise ValueError("empty component")

    value = int(component, 16)
    max_value = (16 ** len(component)) - 1
    if max_value <= 0:
        raise ValueError("invalid component width")

    scaled = round((value / float(max_value)) * 255.0)
    return max(0, min(255, int(scaled)))
