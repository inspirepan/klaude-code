"""Base classes for authentication token management."""

import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

from filelock import FileLock, Timeout
from pydantic import BaseModel

from klaude_code.auth.store import delete_store, load_store, save_store

KLAUDE_AUTH_FILE = Path.home() / ".klaude" / "klaude-auth.json"
# Maximum time to wait for lock acquisition. A holder can legitimately spend a
# slow token request inside the lock (ChatGPT allows 40s of connect wait plus a
# 30s read), so a waiter must outlast that instead of failing while another
# process is still refreshing.
LOCK_TIMEOUT_SECONDS = 120


class BaseAuthState(BaseModel):
    access_token: str
    refresh_token: str
    expires_at: int  # Unix timestamp

    def is_expired(self, buffer_seconds: int = 300) -> bool:
        return time.time() + buffer_seconds >= self.expires_at


class BaseTokenManager[T: BaseAuthState](ABC):
    def __init__(self, auth_file: Path | None = None):
        self.auth_file = auth_file or KLAUDE_AUTH_FILE
        self._state: T | None = None

    @property
    @abstractmethod
    def storage_key(self) -> str:
        """Key used to store this auth state in the JSON file."""
        ...

    @abstractmethod
    def _create_state(self, data: dict[str, Any]) -> T: ...

    def load(self) -> T | None:
        data: Any = load_store(self.auth_file).get(self.storage_key)
        if not isinstance(data, dict):
            return None
        try:
            self._state = self._create_state(cast(dict[str, Any], data))
            return self._state
        except ValueError:
            return None

    def save(self, state: T) -> None:
        store = load_store(self.auth_file)
        store[self.storage_key] = state.model_dump(mode="json")
        save_store(self.auth_file, store)
        self._state = state

    def delete(self) -> None:
        """Delete stored tokens after any in-flight refresh finishes."""
        with FileLock(self._get_lock_file(), timeout=LOCK_TIMEOUT_SECONDS):
            store = load_store(self.auth_file)
            store.pop(self.storage_key, None)
            if not store:
                delete_store(self.auth_file)
            else:
                save_store(self.auth_file, store)
            self._state = None

    def is_logged_in(self) -> bool:
        state = self._state or self.load()
        return state is not None

    def get_state(self) -> T | None:
        if self._state is None:
            self._state = self.load()
        return self._state

    def clear_cached_state(self) -> None:
        """Clear in-memory cached state to force reload from file on next access."""
        self._state = None

    def _get_lock_file(self) -> Path:
        return self.auth_file.with_suffix(".lock")

    def refresh_with_lock(self, refresh_fn: Callable[[T], T]) -> T:
        """Serialize refreshes across processes and reuse tokens refreshed by another instance."""
        lock_file = self._get_lock_file()
        lock = FileLock(lock_file, timeout=LOCK_TIMEOUT_SECONDS)

        try:
            with lock:
                # Re-read file after acquiring lock - another instance may have refreshed
                self.clear_cached_state()
                state = self.load()

                if state is None:
                    raise ValueError(f"Not logged in to {self.storage_key}")

                if not state.is_expired():
                    return state

                new_state = refresh_fn(state)
                self.save(new_state)
                return new_state

        except Timeout:
            # Lock timeout - try to re-read file in case another instance succeeded
            self.clear_cached_state()
            state = self.load()
            if state and not state.is_expired():
                return state
            raise
