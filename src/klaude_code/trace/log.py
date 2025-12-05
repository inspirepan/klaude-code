import logging
from collections.abc import Iterable
from enum import Enum
from logging.handlers import RotatingFileHandler

from rich.console import Console
from rich.logging import RichHandler
from rich.text import Text

from klaude_code import const

# Module-level logger
logger = logging.getLogger("klaude_code")
logger.setLevel(logging.DEBUG)

# Console for direct output (user-facing messages)
log_console = Console()


class DebugType(str, Enum):
    """Debug message categories for filtering."""

    GENERAL = "general"
    LLM_CONFIG = "llm_config"
    LLM_PAYLOAD = "llm_payload"
    LLM_STREAM = "llm_stream"
    UI_EVENT = "ui_event"
    RESPONSE = "response"
    EXECUTION = "execution"
    TERMINAL = "terminal"


class DebugTypeFilter(logging.Filter):
    """Filter log records based on DebugType."""

    def __init__(self, allowed_types: set[DebugType] | None = None):
        super().__init__()
        self.allowed_types = allowed_types

    def filter(self, record: logging.LogRecord) -> bool:
        if self.allowed_types is None:
            return True
        debug_type = getattr(record, "debug_type", DebugType.GENERAL)
        return debug_type in self.allowed_types


# Handler references for reconfiguration
_file_handler: RotatingFileHandler | None = None
_console_handler: RichHandler | None = None
_debug_filter: DebugTypeFilter | None = None
_debug_enabled = False


def set_debug_logging(
    enabled: bool,
    *,
    write_to_file: bool | None = None,
    log_file: str | None = None,
    filters: set[DebugType] | None = None,
) -> None:
    """Configure global debug logging behavior.

    Args:
        enabled: Enable or disable debug logging
        write_to_file: If True, write to file; if False, output to console
        log_file: Path to the log file (default: debug.log)
        filters: Set of DebugType to include; None means all types
    """
    global _file_handler, _console_handler, _debug_filter, _debug_enabled

    _debug_enabled = enabled

    # Remove existing handlers
    if _file_handler is not None:
        logger.removeHandler(_file_handler)
        _file_handler.close()
        _file_handler = None
    if _console_handler is not None:
        logger.removeHandler(_console_handler)
        _console_handler = None

    if not enabled:
        return

    # Create filter
    _debug_filter = DebugTypeFilter(filters)

    # Determine output mode
    use_file = write_to_file if write_to_file is not None else True
    file_path = log_file if log_file is not None else const.DEFAULT_DEBUG_LOG_FILE

    if use_file:
        _file_handler = RotatingFileHandler(
            file_path,
            maxBytes=const.LOG_MAX_BYTES,
            backupCount=const.LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
        _file_handler.setLevel(logging.DEBUG)
        _file_handler.setFormatter(logging.Formatter("[%(asctime)s] %(debug_type_label)-12s %(message)s"))
        _file_handler.addFilter(_debug_filter)
        logger.addHandler(_file_handler)
    else:
        # Console handler with Rich formatting
        _console_handler = RichHandler(
            console=log_console,
            show_time=False,
            show_path=False,
            rich_tracebacks=True,
        )
        _console_handler.setLevel(logging.DEBUG)
        _console_handler.addFilter(_debug_filter)
        logger.addHandler(_console_handler)


def log(*objects: str | tuple[str, str], style: str = "") -> None:
    """Output user-facing messages to console.

    Args:
        objects: Strings or (text, style) tuples to print
        style: Default style for all objects
    """
    log_console.print(
        *((Text(obj[0], style=obj[1]) if isinstance(obj, tuple) else Text(obj)) for obj in objects),
        style=style,
    )


def log_debug(
    *objects: str | tuple[str, str],
    style: str | None = None,
    debug_type: DebugType = DebugType.GENERAL,
) -> None:
    """Log debug messages with category support.

    Args:
        objects: Strings or (text, style) tuples to log
        style: Style hint (used for console output)
        debug_type: Category of the debug message
    """
    if not _debug_enabled:
        return

    message = _build_message(objects)

    # Create log record with extra fields
    extra = {
        "debug_type": debug_type,
        "debug_type_label": debug_type.value.upper(),
        "style": style,
    }
    logger.debug(message, extra=extra)


def _build_message(objects: Iterable[str | tuple[str, str]]) -> str:
    """Build plain text message from objects."""
    parts: list[str] = []
    for obj in objects:
        if isinstance(obj, tuple):
            parts.append(obj[0])
        else:
            parts.append(obj)
    return " ".join(parts)


def is_debug_enabled() -> bool:
    """Check if debug logging is currently enabled."""
    return _debug_enabled
