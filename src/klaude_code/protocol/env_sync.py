"""Wire framing for client env sync with the local server.

The server daemon's ``os.environ`` is frozen at launch, so each REST client
attaches the env vars its config references (see
``Config.referenced_env_values``) as a header; the server middleware merges
them into its own ``os.environ`` before answering. The framing lives here so
both REST clients (``cli/uds_client``, ``tui/client/server_api``), the server
middleware, and tests share one codec. Mirror of ``protocol/version.py``:
small, dependency-free, bottom-layer.
"""

from __future__ import annotations

import base64
import json
import re

#: HTTP header carrying the client's referenced env vars (base64 JSON object).
ENV_SYNC_HEADER = "X-Klaude-Env"
#: Lowercased form as it appears in ASGI scope header tuples.
ENV_SYNC_HEADER_ASGI = b"x-klaude-env"

_ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def encode_env_header(values: dict[str, str]) -> str:
    """Encode {name: value} env vars as a header-safe ASCII string."""
    payload = json.dumps(values, sort_keys=True).encode("utf-8")
    return base64.b64encode(payload).decode("ascii")


def decode_env_header(raw: str | bytes) -> dict[str, str] | None:
    """Decode a header value; return None when malformed or not an object."""
    try:
        if isinstance(raw, bytes):
            payload = json.loads(base64.b64decode(raw).decode("utf-8"))
        else:
            payload = json.loads(base64.b64decode(raw.encode("ascii")).decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return {
        str(name): str(value)
        for name, value in payload.items()
        if isinstance(name, str) and isinstance(value, str) and _ENV_NAME_RE.match(name)
    }
