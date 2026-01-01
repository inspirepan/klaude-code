"""Base classes for authentication token management."""

import json
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel


KLAUDE_AUTH_FILE = Path.home() / ".klaude" / "klaude-auth.json"


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
