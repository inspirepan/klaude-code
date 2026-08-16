"""Small REST helpers against the local klaude server (UDS HTTP).

Lives in the tui layer (not cli) so the runner can create sessions for
/new without a layering violation.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def _request(method: str, path: str, *, json_body: dict[str, Any] | None = None, timeout: float = 30.0) -> Any:
    import httpx

    from klaude_code.server.paths import server_socket_path

    transport = httpx.HTTPTransport(uds=str(server_socket_path()))
    with httpx.Client(transport=transport, base_url="http://klaude", timeout=timeout) as client:
        response = client.request(method, path, json=json_body)
    if response.status_code >= 400:
        detail: Any
        try:
            detail = response.json().get("detail")
        except Exception:
            detail = response.text
        raise RuntimeError(f"server error {response.status_code}: {detail}")
    return response.json()


def enable_server_debug_logging() -> Path:
    """Enable debug file logging on the server; return the log path."""
    body = _request("POST", "/api/server/debug", json_body={"enabled": True}, timeout=5.0)
    log_file = body.get("log_file")
    if not isinstance(log_file, str) or not log_file:
        raise RuntimeError("server did not return a debug log file")
    return Path(log_file)


def reload_server_config() -> str | None:
    """Ask the server to re-read ~/.klaude/klaude-config.yaml.

    Config changes written by a client (e.g. /manage-providers) are invisible to
    the server until it drops its cached copy. Best-effort: returns an error
    message when the server is unreachable or rejects the new file, so the caller
    can surface it instead of failing the command.
    """
    try:
        _request("POST", "/api/server/config/reload", timeout=5.0)
    except Exception as exc:
        return str(exc)
    return None


def create_server_session(*, work_dir: Path, model: str | None = None, vanilla: bool = False) -> str:
    """Create a new session on the server; return its id."""
    body = _request(
        "POST",
        "/api/sessions",
        json_body={"work_dir": str(work_dir), "model": model, "vanilla": vanilla},
    )
    session_id = body.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        raise RuntimeError("server did not return a session id")
    return session_id
