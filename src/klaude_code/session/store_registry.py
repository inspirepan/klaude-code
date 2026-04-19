from __future__ import annotations

from pathlib import Path

from klaude_code.const import project_key_from_path
from klaude_code.session.store import JsonlSessionStore

_DEFAULT_STORES: dict[str, JsonlSessionStore] = {}


def get_store_for_path(work_dir: Path) -> JsonlSessionStore:
    """Return a session store for the given work directory."""
    project_key = project_key_from_path(work_dir)
    store = _DEFAULT_STORES.get(project_key)
    if store is None:
        store = JsonlSessionStore(project_key=project_key)
        _DEFAULT_STORES[project_key] = store
    return store


async def close_default_store() -> None:
    stores = list(_DEFAULT_STORES.values())
    _DEFAULT_STORES.clear()
    for store in stores:
        await store.aclose()


__all__ = ["close_default_store", "get_store_for_path"]