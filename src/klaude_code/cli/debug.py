"""Debug utilities for CLI."""

from pathlib import Path

from klaude_code.log import prepare_debug_log_file


def prepare_debug_logging(debug: bool) -> tuple[bool, Path | None]:
    """Prepare log file if debug is enabled.

    Returns:
        A tuple of (debug_enabled, log_path).
        log_path is None if debugging is disabled.
    """
    log_path: Path | None = None
    if debug:
        log_path = prepare_debug_log_file()
    return debug, log_path
