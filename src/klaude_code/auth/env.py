"""Environment variable configuration stored in klaude-auth.json."""

import json
from typing import Any

from klaude_code.auth.base import KLAUDE_AUTH_FILE


def _load_store() -> dict[str, Any]:
    """Load the auth store from file."""
    if not KLAUDE_AUTH_FILE.exists():
        return {}
    try:
        data: Any = json.loads(KLAUDE_AUTH_FILE.read_text())
        if isinstance(data, dict):
            return dict(data)
        return {}
    except (json.JSONDecodeError, ValueError):
        return {}


def _save_store(data: dict[str, Any]) -> None:
    """Save the auth store to file."""
    KLAUDE_AUTH_FILE.parent.mkdir(parents=True, exist_ok=True)
    KLAUDE_AUTH_FILE.write_text(json.dumps(data, indent=2))


def get_auth_env(env_var: str) -> str | None:
    """Get environment variable value from klaude-auth.json 'env' section.

    This provides a fallback for API keys when real environment variables are not set.
    Priority: os.environ > klaude-auth.json env
    """
    store = _load_store()
    env_section: Any = store.get("env")
    if not isinstance(env_section, dict):
        return None
    value: Any = env_section.get(env_var)
    return str(value) if value is not None else None


def set_auth_env(env_var: str, value: str) -> None:
    """Set environment variable value in klaude-auth.json 'env' section."""
    store = _load_store()
    env_section: Any = store.get("env")
    if not isinstance(env_section, dict):
        env_section = {}
    env_section[env_var] = value
    store["env"] = env_section
    _save_store(store)


def delete_auth_env(env_var: str) -> None:
    """Delete environment variable from klaude-auth.json 'env' section."""
    store = _load_store()
    env_section: Any = store.get("env")
    if not isinstance(env_section, dict):
        return
    env_section.pop(env_var, None)
    if len(env_section) == 0:
        store.pop("env", None)
    else:
        store["env"] = env_section
    if len(store) == 0:
        if KLAUDE_AUTH_FILE.exists():
            KLAUDE_AUTH_FILE.unlink()
    else:
        _save_store(store)


def list_auth_env() -> dict[str, str]:
    """List all environment variables in klaude-auth.json 'env' section."""
    store = _load_store()
    env_section: Any = store.get("env")
    if not isinstance(env_section, dict):
        return {}
    return {k: str(v) for k, v in env_section.items() if v is not None}
