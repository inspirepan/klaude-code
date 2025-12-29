from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from enum import Enum
from typing import TextIO, cast

from klaude_code.trace import DebugType, log_debug

# Environment variable for tmux test signal channel
TMUX_SIGNAL_ENV = "KLAUDE_TEST_SIGNAL"

ST = "\033\\"
BEL = "\a"


def resolve_stream(stream: TextIO | None) -> TextIO:
    """Use the original stdout when available to avoid interception by Rich wrappers."""
    if stream is not None:
        return stream
    if hasattr(sys, "__stdout__") and sys.__stdout__ is not None:
        return cast(TextIO, sys.__stdout__)
    return sys.stdout


class NotificationType(Enum):
    AGENT_TASK_COMPLETE = "agent_task_complete"


@dataclass
class Notification:
    type: NotificationType
    title: str
    body: str | None = None


@dataclass
class TerminalNotifierConfig:
    enabled: bool = True
    use_bel: bool = False
    stream: TextIO | None = None

    @classmethod
    def from_env(cls) -> TerminalNotifierConfig:
        env = os.getenv("KLAUDE_NOTIFY", "").strip().lower()
        if env in {"0", "off", "false", "disable", "disabled"}:
            return cls(enabled=False)
        return cls(enabled=True)


class TerminalNotifier:
    def __init__(self, config: TerminalNotifierConfig | None = None) -> None:
        self.config = config or TerminalNotifierConfig.from_env()

    def notify(self, notification: Notification) -> bool:
        if not self.config.enabled:
            log_debug(
                "Terminal notifier skipped: disabled via config",
                debug_type=DebugType.TERMINAL,
            )
            return False

        output = resolve_stream(self.config.stream)
        if not self._supports_osc9(output):
            log_debug(
                "Terminal notifier skipped: OSC 9 unsupported or not a TTY",
                debug_type=DebugType.TERMINAL,
            )
            return False

        payload = self._render_payload(notification)
        return self._emit(payload, output)

    def _render_payload(self, notification: Notification) -> str:
        title = _compact(notification.title)
        body = _compact(notification.body) if notification.body else None
        if body:
            return f"{title} - {body}"
        return title

    def _emit(self, payload: str, output: TextIO) -> bool:
        terminator = BEL if self.config.use_bel else ST
        seq = f"\033]9;{payload}{terminator}"
        try:
            output.write(seq)
            output.flush()
            log_debug("Terminal notifier sent OSC 9 payload", debug_type=DebugType.TERMINAL)
            return True
        except Exception as exc:
            log_debug(f"Terminal notifier send failed: {exc}", debug_type=DebugType.TERMINAL)
            return False

    @staticmethod
    def _supports_osc9(stream: TextIO) -> bool:
        if sys.platform == "win32":
            return False
        if not getattr(stream, "isatty", lambda: False)():
            return False
        term = os.getenv("TERM", "")
        return term.lower() not in {"", "dumb"}


def _compact(text: str, limit: int = 160) -> str:
    squashed = " ".join(text.split())
    if len(squashed) > limit:
        return squashed[: limit - 3] + "…"
    return squashed


def emit_tmux_signal(channel: str | None = None) -> bool:
    """Send a tmux wait-for signal when a task completes.

    This enables synchronous testing by allowing external scripts to block
    until a task finishes, eliminating the need for polling or sleep.

    Usage:
        KLAUDE_TEST_SIGNAL=done klaude  # In tmux session
        tmux wait-for done              # Blocks until task completes

    Args:
        channel: Signal channel name. If None, reads from KLAUDE_TEST_SIGNAL env var.

    Returns:
        True if signal was sent successfully, False otherwise.
    """
    channel = channel or os.getenv(TMUX_SIGNAL_ENV)
    if not channel:
        return False

    # Check if we're in a tmux session
    if not os.getenv("TMUX"):
        log_debug("tmux signal skipped: not in tmux session", debug_type=DebugType.TERMINAL)
        return False

    try:
        subprocess.run(
            ["tmux", "wait-for", "-S", channel],
            check=True,
            capture_output=True,
        )
        log_debug(f"tmux signal sent: {channel}", debug_type=DebugType.TERMINAL)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        log_debug(f"tmux signal failed: {e}", debug_type=DebugType.TERMINAL)
        return False
