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
