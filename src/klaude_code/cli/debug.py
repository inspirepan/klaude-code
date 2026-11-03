"""Debug utilities for CLI."""

from pathlib import Path


def prepare_debug_logging(debug: bool) -> tuple[bool, Path | None]:
    """Enable debug logging in the process that owns execution.

    Returns:
        A tuple of (debug_enabled, log_path).
        log_path is None if debugging is disabled.
    """
    if not debug:
        return False, None

    from klaude_code.log import get_current_log_file, set_debug_logging

    set_debug_logging(True)
    return True, get_current_log_file()
