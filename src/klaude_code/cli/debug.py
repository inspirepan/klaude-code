"""Debug utilities for CLI."""

from pathlib import Path

import typer

from klaude_code.log import DebugType, log, prepare_debug_log_file

DEBUG_FILTER_HELP = "Comma-separated debug types: " + ", ".join(dt.value for dt in DebugType)


def parse_debug_filters(raw: str | None) -> set[DebugType] | None:
    """Parse comma-separated debug filter string into a set of DebugType."""
    if raw is None:
        return None
    filters: set[DebugType] = set()
    for chunk in raw.split(","):
        normalized = chunk.strip().lower().replace("-", "_")
        if not normalized:
            continue
        try:
            filters.add(DebugType(normalized))
        except ValueError:  # pragma: no cover - user input validation
            valid_options = ", ".join(dt.value for dt in DebugType)
            log(
                (
                    f"Invalid debug filter '{normalized}'. Valid options: {valid_options}",
                    "red",
                )
            )
            raise typer.Exit(2) from None
    return filters or None


def resolve_debug_settings(flag: bool, raw_filters: str | None) -> tuple[bool, set[DebugType] | None]:
    """Resolve debug flag and filters into effective settings."""
    filters = parse_debug_filters(raw_filters)
    effective_flag = flag or (filters is not None)
    return effective_flag, filters


def prepare_debug_logging(debug: bool, debug_filter: str | None) -> tuple[bool, set[DebugType] | None, Path | None]:
    """Resolve debug settings and prepare log file if enabled.

    Returns:
        A tuple of (debug_enabled, debug_filters, log_path).
        log_path is None if debugging is disabled.
    """

    debug_enabled, debug_filters = resolve_debug_settings(debug, debug_filter)
    log_path: Path | None = None
    if debug_enabled:
        log_path = prepare_debug_log_file()
    return debug_enabled, debug_filters, log_path
