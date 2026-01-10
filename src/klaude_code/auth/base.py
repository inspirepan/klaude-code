"""Base classes for authentication token management."""

import json
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

from filelock import FileLock, Timeout
from pydantic import BaseModel

KLAUDE_AUTH_FILE = Path.home() / ".klaude" / "klaude-auth.json"
LOCK_TIMEOUT_SECONDS = 30  # Maximum time to wait for lock acquisition


class BaseAuthState(BaseModel):
    """Base authentication state with common OAuth fields."""

    access_token: str
    refresh_token: str
    expires_at: int  # Unix timestamp

    def is_expired(self, buffer_seconds: int = 300) -> bool:
        """Check if token is expired or will expire soon."""
        return time.time() + buffer_seconds >= self.expires_at


class BaseTokenManager[T: BaseAuthState](ABC):
    """Base class for OAuth token management."""

    def __init__(self, auth_file: Path | None = None):
        self.auth_file = auth_file or KLAUDE_AUTH_FILE
        self._state: T | None = None

    @property
    @abstractmethod
    def storage_key(self) -> str:
        """Key used to store this auth state in the JSON file."""
        ...

    @abstractmethod
    def _create_state(self, data: dict[str, Any]) -> T:
        """Create state instance from dict data."""
        ...

    def _load_store(self) -> dict[str, Any]:
        if not self.auth_file.exists():
            return {}
        try:
            data: Any = json.loads(self.auth_file.read_text())
            if isinstance(data, dict):
                return cast(dict[str, Any], data)
            return {}
        except (json.JSONDecodeError, ValueError):
            return {}

    def _save_store(self, data: dict[str, Any]) -> None:
        self.auth_file.parent.mkdir(parents=True, exist_ok=True)
        self.auth_file.write_text(json.dumps(data, indent=2))

    def load(self) -> T | None:
        """Load authentication state from file."""
        data: Any = self._load_store().get(self.storage_key)
        if not isinstance(data, dict):
            return None
        try:
            self._state = self._create_state(cast(dict[str, Any], data))
            return self._state
        except ValueError:
            return None

    def save(self, state: T) -> None:
        """Save authentication state to file."""
        store = self._load_store()
        store[self.storage_key] = state.model_dump(mode="json")
        self._save_store(store)
        self._state = state

    def delete(self) -> None:
        """Delete stored tokens."""
        store = self._load_store()
        store.pop(self.storage_key, None)
        if len(store) == 0:
            if self.auth_file.exists():
                self.auth_file.unlink()
        else:
            self._save_store(store)
        self._state = None

    def is_logged_in(self) -> bool:
        """Check if user is logged in."""
        state = self._state or self.load()
        return state is not None

    def get_state(self) -> T | None:
        """Get current authentication state."""
        if self._state is None:
            self._state = self.load()
        return self._state

    def clear_cached_state(self) -> None:
        """Clear in-memory cached state to force reload from file on next access."""
        self._state = None

    def _get_lock_file(self) -> Path:
        """Get the lock file path for this auth file."""
        return self.auth_file.with_suffix(".lock")

    def refresh_with_lock(self, refresh_fn: Callable[[T], T]) -> T:
        """Refresh token with file locking to prevent concurrent refresh.

        This prevents multiple instances from simultaneously refreshing the same token.
        If another instance has already refreshed, returns the updated state.

        Args:
            refresh_fn: Function that takes current state and returns new state.

        Returns:
            The new or already-refreshed authentication state.

        Raises:
            Timeout: If unable to acquire the lock within timeout.
            ValueError: If not logged in.
        """
        lock_file = self._get_lock_file()
        lock = FileLock(lock_file, timeout=LOCK_TIMEOUT_SECONDS)

        try:
            with lock:
                # Re-read file after acquiring lock - another instance may have refreshed
                self.clear_cached_state()
                state = self.load()

                if state is None:
                    raise ValueError(f"Not logged in to {self.storage_key}")

                # Check if token is still expired after re-reading
                if not state.is_expired():
                    # Another instance already refreshed, use their result
                    return state

                # Token still expired, we need to refresh
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
