from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from enum import Enum
from typing import TextIO, cast

from klaude_code.const import NOTIFY_COMPACT_LIMIT
from klaude_code.log import DebugType, log_debug

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
    ASK_USER_QUESTION = "ask_user_question"


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
        if not self._supports_notification(output):
            log_debug(
                "Terminal notifier skipped: not a TTY",
                debug_type=DebugType.TERMINAL,
            )
            return False

        payload = self._render_payload(notification)
        return self._emit(payload, output)

    def _render_payload(self, notification: Notification) -> tuple[str, str]:
        """Return (title, body) for OSC 777 notification."""
        body = _compact(notification.body) if notification.body else _compact(notification.title)
        return ("klaude", body)

    def _emit(self, payload: tuple[str, str], output: TextIO) -> bool:
        terminator = BEL if self.config.use_bel else ST
        title, body = payload
        seq = f"\033]777;notify;{title};{body}{terminator}"
        try:
            output.write(seq)
            output.flush()
            log_debug("Terminal notifier sent OSC 777 payload", debug_type=DebugType.TERMINAL)
            return True
        except Exception as exc:
            log_debug(f"Terminal notifier send failed: {exc}", debug_type=DebugType.TERMINAL)
            return False

    @staticmethod
    def _supports_notification(stream: TextIO) -> bool:
        if sys.platform == "win32":
            return False
        if not getattr(stream, "isatty", lambda: False)():
            return False
        term = os.getenv("TERM", "")
        return term.lower() not in {"", "dumb"}


def _compact(text: str, limit: int = NOTIFY_COMPACT_LIMIT) -> str:
    squashed = " ".join(text.split())
    if len(squashed) > limit:
        return squashed[: limit - 3] + "…"
    return squashed

