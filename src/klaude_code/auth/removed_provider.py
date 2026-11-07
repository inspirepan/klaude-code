"""Cleanup helpers for auth providers that have been removed."""

from klaude_code.auth import base
from klaude_code.auth.store import delete_store, load_store, save_store

_REMOVED_GITHUB_COPILOT_STORAGE_KEYS = ("github-copilot", "copilot")


def has_removed_github_copilot_auth_state() -> bool:
    store = load_store(base.KLAUDE_AUTH_FILE)
    return any(key in store for key in _REMOVED_GITHUB_COPILOT_STORAGE_KEYS)


def delete_removed_github_copilot_auth_state() -> bool:
    store = load_store(base.KLAUDE_AUTH_FILE)
    changed = False
    for key in _REMOVED_GITHUB_COPILOT_STORAGE_KEYS:
        changed = store.pop(key, None) is not None or changed
    if not changed:
        return False
    if store:
        save_store(base.KLAUDE_AUTH_FILE, store)
    else:
        delete_store(base.KLAUDE_AUTH_FILE)
    return True
