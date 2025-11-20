from __future__ import annotations

import builtins
import io
import os
from typing import Any, Callable

import pytest

from codex_mini.ui.base import terminal_color


class DummyTTY(io.BytesIO):
    """Minimal /dev/tty stand-in used for OSC write tests."""

    def __init__(self) -> None:  # pragma: no cover - trivial
        super().__init__()
        self._fileno = 42

    def fileno(self) -> int:  # pragma: no cover - trivial
        return self._fileno


def _make_dummy_open(real_open: Callable[..., Any]) -> Callable[..., Any]:
    """Return an open() replacement that yields DummyTTY for /dev/tty only."""

    def _open(path: str, *args: Any, **kwargs: Any) -> Any:
        if path == "/dev/tty":
            return DummyTTY()
        return real_open(path, *args, **kwargs)

    return _open


def test_query_color_slot_parses_osc_response(monkeypatch: pytest.MonkeyPatch) -> None:
    """_query_color_slot should parse a basic OSC 11 rgb: reply into 0-255 RGB."""

    # Ensure platform and TERM look supported
    monkeypatch.setattr(terminal_color.sys, "platform", "darwin")
    monkeypatch.setenv("TERM", "xterm-256color")

    # Make /dev/tty behave like a TTY without touching the real terminal
    real_open = builtins.open
    monkeypatch.setattr(builtins, "open", _make_dummy_open(real_open))
    monkeypatch.setattr(terminal_color.os, "isatty", lambda fd: True)

    # Avoid manipulating real termios/tty state
    monkeypatch.setattr(terminal_color.termios, "tcgetattr", lambda fd: object())
    monkeypatch.setattr(terminal_color.termios, "tcsetattr", lambda fd, when, attrs: None)
    monkeypatch.setattr(terminal_color.tty, "setcbreak", lambda fd: None)

    # Short-circuit the read path: pretend the terminal replied with a red background
    osc_reply = b"\x1b]11;rgb:ffff/0000/0000\x07"
    monkeypatch.setattr(terminal_color, "_read_osc_response", lambda fd, timeout: osc_reply)

    rgb = terminal_color._query_color_slot(slot=11, timeout=0.1)
    assert rgb is not None
    r, g, b = rgb
    # rgb:ffff/0000/0000 should map close to pure red
    assert r == 255
    assert g == 0
    assert b == 0


def test_is_light_terminal_background_luminance(monkeypatch: pytest.MonkeyPatch) -> None:
    """is_light_terminal_background should apply the expected luminance threshold."""

    # Light background case: white
    monkeypatch.setattr(terminal_color, "_query_color_slot", lambda slot, timeout: (255, 255, 255))
    assert terminal_color.is_light_terminal_background() is True

    # Dark background case: black
    monkeypatch.setattr(terminal_color, "_query_color_slot", lambda slot, timeout: (0, 0, 0))
    assert terminal_color.is_light_terminal_background() is False

    # Detection failed
    monkeypatch.setattr(terminal_color, "_query_color_slot", lambda slot, timeout: None)
    assert terminal_color.is_light_terminal_background() is None
