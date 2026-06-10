"""Cleanup helpers for auth providers that have been removed."""

import json
from typing import Any, cast

from klaude_code.auth import base

_REMOVED_GITHUB_COPILOT_STORAGE_KEYS = ("github-copilot", "copilot")


def has_removed_github_copilot_auth_state() -> bool:
    """Return whether legacy GitHub Copilot OAuth state is still stored."""
    store = _load_store()
    return any(key in store for key in _REMOVED_GITHUB_COPILOT_STORAGE_KEYS)


def delete_removed_github_copilot_auth_state() -> bool:
    """Delete legacy GitHub Copilot OAuth state from the auth store."""
    store = _load_store()
    changed = False
    for key in _REMOVED_GITHUB_COPILOT_STORAGE_KEYS:
        changed = store.pop(key, None) is not None or changed
    if not changed:
        return False
    if store:
        _save_store(store)
    elif base.KLAUDE_AUTH_FILE.exists():
        base.KLAUDE_AUTH_FILE.unlink()
    return True


def _load_store() -> dict[str, Any]:
    if not base.KLAUDE_AUTH_FILE.exists():
        return {}
    try:
        data: Any = json.loads(base.KLAUDE_AUTH_FILE.read_text())
    except (json.JSONDecodeError, ValueError):
        return {}
    if isinstance(data, dict):
        return cast(dict[str, Any], data)
    return {}


def _save_store(data: dict[str, Any]) -> None:
    base.KLAUDE_AUTH_FILE.parent.mkdir(parents=True, exist_ok=True)
    base.KLAUDE_AUTH_FILE.write_text(json.dumps(data, indent=2))