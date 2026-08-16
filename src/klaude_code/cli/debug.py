"""Debug utilities for CLI."""

from pathlib import Path


def prepare_debug_logging(debug: bool) -> tuple[bool, Path | None]:
    """Enable debug logging on the local server when requested.

    Agent/LLM work lives in the server process. Creating a client-side log
    file would leave the viewer pointed at an empty path.

    Returns:
        A tuple of (debug_enabled, log_path).
        log_path is None if debugging is disabled.
    """
    if not debug:
        return False, None

    from klaude_code.cli.uds_client import request

    status, body = request("POST", "/api/server/debug", json_body={"enabled": True})
    if status != 200 or not isinstance(body, dict):
        detail = body.get("detail") if isinstance(body, dict) else body
        raise RuntimeError(f"failed to enable server debug logging: {detail}")
    log_file = body.get("log_file")
    if not isinstance(log_file, str) or not log_file:
        raise RuntimeError("server did not return a debug log file")
    return True, Path(log_file)
