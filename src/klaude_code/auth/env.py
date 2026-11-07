"""Environment variable configuration stored in klaude-auth.json."""

from typing import Any, cast

from klaude_code.auth import base
from klaude_code.auth.store import delete_store, load_store, save_store


def _get_env_section(store: dict[str, Any]) -> dict[str, Any] | None:
    env_section = store.get("env")
    if isinstance(env_section, dict):
        return cast(dict[str, Any], env_section)
    return None


def get_auth_env(env_var: str) -> str | None:
    """Provide a stored fallback when the caller finds no real environment variable."""
    env_section = _get_env_section(load_store(base.KLAUDE_AUTH_FILE))
    if env_section is None:
        return None
    value = env_section.get(env_var)
    return str(value) if value is not None else None


def set_auth_env(env_var: str, value: str) -> None:
    store = load_store(base.KLAUDE_AUTH_FILE)
    env_section = _get_env_section(store) or {}
    env_section[env_var] = value
    store["env"] = env_section
    save_store(base.KLAUDE_AUTH_FILE, store)


def delete_auth_env(env_var: str) -> None:
    store = load_store(base.KLAUDE_AUTH_FILE)
    env_section = _get_env_section(store)
    if env_section is None:
        return
    env_section.pop(env_var, None)
    if not env_section:
        store.pop("env", None)
    else:
        store["env"] = env_section
    if not store:
        delete_store(base.KLAUDE_AUTH_FILE)
    else:
        save_store(base.KLAUDE_AUTH_FILE, store)


def list_auth_env() -> dict[str, str]:
    env_section = _get_env_section(load_store(base.KLAUDE_AUTH_FILE))
    if env_section is None:
        return {}
    return {k: str(v) for k, v in env_section.items() if v is not None}
