from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Iterable

from rich.console import Console
from rich.text import Text


class DebugType(str, Enum):
    GENERAL = "general"
    LLM_CONFIG = "llm_config"
    LLM_PAYLOAD = "llm_payload"
    LLM_STREAM = "llm_stream"
    UI_EVENT = "ui_event"
    RESPONSE = "response"
    EXECUTION = "execution"
    TERMINAL = "terminal"


@dataclass(frozen=True)
class DebugChannel:
    label: str
    emoji: str | None
    style: str

    @property
    def console_prefix(self) -> str:
        emoji_prefix = f"{self.emoji} " if self.emoji else ""
        return f"{emoji_prefix}[{self.label}] "

    @property
    def log_prefix(self) -> str:
        return f"[{self.label}]{' ' * (12 - len(self.label))} "


log_console = Console()

_debug_enabled = False
_debug_write_to_file = True
_debug_log_file = "debug.log"
_debug_filters: set[DebugType] | None = None

_DEBUG_CHANNELS: dict[DebugType, DebugChannel] = {
    DebugType.GENERAL: DebugChannel(label="GENERAL", emoji=None, style="blue"),
    DebugType.LLM_CONFIG: DebugChannel(label="LLM CONFIG", emoji="➡️", style="yellow"),
    DebugType.LLM_PAYLOAD: DebugChannel(label="LLM PAYLOAD", emoji="➡️", style="yellow"),
    DebugType.LLM_STREAM: DebugChannel(label="LLM STREAM", emoji="📥", style="blue"),
    DebugType.UI_EVENT: DebugChannel(label="UI", emoji="🧩", style="magenta"),
    DebugType.RESPONSE: DebugChannel(label="RESPONSE", emoji="📁", style="cyan"),
    DebugType.EXECUTION: DebugChannel(label="EXECUTION", emoji="⚙️", style="green"),
    DebugType.TERMINAL: DebugChannel(label="TERMINAL", emoji="⌨️", style="white"),
}


def set_debug_logging(
    enabled: bool,
    *,
    write_to_file: bool | None = None,
    log_file: str | None = None,
    filters: set[DebugType] | None = None,
) -> None:
    """Configure global debug logging behavior."""

    global _debug_enabled, _debug_write_to_file, _debug_log_file, _debug_filters

    _debug_enabled = enabled
    _debug_filters = set(filters) if filters is not None else None
    if write_to_file is not None:
        _debug_write_to_file = write_to_file
    if log_file is not None:
        _debug_log_file = log_file


def log(*objects: str | tuple[str, str], style: str = "") -> None:
    log_console.print(
        *((Text(obj[0], style=obj[1]) if isinstance(obj, tuple) else Text(obj)) for obj in objects), style=style
    )


def log_debug(
    *objects: str | tuple[str, str],
    style: str | None = None,
    debug_type: DebugType = DebugType.GENERAL,
) -> None:
    if not _debug_enabled:
        return

    if _debug_filters is not None and debug_type not in _debug_filters:
        return

    channel = _DEBUG_CHANNELS.get(debug_type, _DEBUG_CHANNELS[DebugType.GENERAL])

    resolved_style = style or channel.style
    if _debug_write_to_file:
        message = _build_plain_message(channel.log_prefix, objects)
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(_debug_log_file, "a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] {message}\n")
    else:
        prefixed_objects: tuple[str | tuple[str, str], ...] = _prepend_prefix(channel.console_prefix, objects)
        log_console.print(
            *((Text(obj[0], style=obj[1]) if isinstance(obj, tuple) else Text(obj)) for obj in prefixed_objects),
            style=resolved_style,
        )


def _prepend_prefix(prefix: str, objects: Iterable[str | tuple[str, str]]) -> tuple[str | tuple[str, str], ...]:
    prefixed: list[str | tuple[str, str]] = [prefix]
    prefixed.extend(objects)
    return tuple(prefixed)


def _build_plain_message(prefix: str, objects: Iterable[str | tuple[str, str]]) -> str:
    message_parts = [prefix]
    for obj in objects:
        if isinstance(obj, tuple):
            message_parts.append(obj[0])  # type: ignore[arg-type]
        else:
            message_parts.append(obj)  # type: ignore[arg-type]
    return " ".join(message_parts)
