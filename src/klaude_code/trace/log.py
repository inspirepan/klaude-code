import gzip
import logging
import os
import shutil
import subprocess
from collections.abc import Iterable
from datetime import datetime, timedelta
from enum import Enum
from logging.handlers import RotatingFileHandler
from pathlib import Path

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
_current_log_file: Path | None = None

LOG_RETENTION_DAYS = 3
LOG_MAX_TOTAL_BYTES = 200 * 1024 * 1024


class GzipRotatingFileHandler(RotatingFileHandler):
    """Rotating file handler that gzips rolled files."""

    def rotation_filename(self, default_name: str) -> str:
        """Append .gz to rotation targets."""

        return f"{default_name}.gz"

    def rotate(self, source: str, dest: str) -> None:
        """Compress the rotated file and remove the original."""

        with open(source, "rb") as source_file, gzip.open(dest, "wb") as dest_file:
            shutil.copyfileobj(source_file, dest_file)
        Path(source).unlink(missing_ok=True)


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
    global _file_handler, _console_handler, _debug_filter, _debug_enabled, _current_log_file

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
        _current_log_file = None
        return

    # Create filter
    _debug_filter = DebugTypeFilter(filters)

    # Determine output mode
    use_file = write_to_file if write_to_file is not None else True
    if use_file:
        if _current_log_file is None:
            _current_log_file = _resolve_log_file(log_file)
        file_path = _current_log_file
    else:
        _current_log_file = None
        file_path = None

    if use_file and file_path is not None:
        _prune_old_logs(const.DEFAULT_DEBUG_LOG_DIR, LOG_RETENTION_DAYS, LOG_MAX_TOTAL_BYTES)

    if use_file and file_path is not None:
        _file_handler = GzipRotatingFileHandler(
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


def prepare_debug_log_file(log_file: str | os.PathLike[str] | None = None) -> Path:
    """Prepare and remember the log file path for this session."""

    global _current_log_file
    _current_log_file = _resolve_log_file(log_file)
    return _current_log_file


def get_current_log_file() -> Path | None:
    """Return the currently active log file path, if any."""

    return _current_log_file


def _resolve_log_file(log_file: str | os.PathLike[str] | None) -> Path:
    """Resolve the log file path and ensure directories exist."""

    if log_file:
        path = Path(log_file).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        return path
    else:
        path = _build_default_log_file_path()

    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch(exist_ok=True)
    _refresh_latest_symlink(path)
    return path


def _build_default_log_file_path() -> Path:
    """Build a per-session log path under the default log directory."""

    now = datetime.now()
    session_dir = const.DEFAULT_DEBUG_LOG_DIR / now.strftime("%Y-%m-%d")
    session_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{now.strftime('%H%M%S')}-{os.getpid()}.log"
    return session_dir / filename


def _refresh_latest_symlink(target: Path) -> None:
    """Point the debug.log symlink at the latest session file."""

    latest = const.DEFAULT_DEBUG_LOG_FILE
    try:
        latest.unlink(missing_ok=True)
        latest.symlink_to(target)
    except OSError:
        # Non-blocking best-effort; logging should still proceed
        return


def _prune_old_logs(log_root: Path, keep_days: int, max_total_bytes: int) -> None:
    """Remove logs older than keep_days or when exceeding max_total_bytes."""

    if not log_root.exists():
        return

    cutoff = datetime.now() - timedelta(days=keep_days)
    files: list[Path] = [p for p in log_root.rglob("*") if p.is_file() and not p.is_symlink()]

    # Remove by age
    for path in files:
        try:
            mtime = datetime.fromtimestamp(path.stat().st_mtime)
        except OSError:
            continue
        if mtime < cutoff:
            _trash_path(path)

    # Recompute remaining files and sizes
    remaining: list[tuple[Path, float, int]] = []
    total_size = 0
    for path in log_root.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        remaining.append((path, stat.st_mtime, stat.st_size))
        total_size += stat.st_size

    if total_size <= max_total_bytes:
        return

    remaining.sort(key=lambda item: item[1])
    for path, _, size in remaining:
        _trash_path(path)
        total_size -= size
        if total_size <= max_total_bytes:
            break


def _trash_path(path: Path) -> None:
    """Send a path to trash, falling back to unlink if trash is unavailable."""

    try:
        subprocess.run(
            ["trash", str(path)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except FileNotFoundError:
        path.unlink(missing_ok=True)
