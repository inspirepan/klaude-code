"""Token storage and management for GitHub Copilot authentication."""

from pathlib import Path
from typing import Any, cast

from klaude_code.auth.base import BaseAuthState, BaseTokenManager


class CopilotAuthState(BaseAuthState):
    """Stored authentication state for GitHub Copilot."""

    enterprise_domain: str | None = None
    copilot_base_url: str = "https://api.individual.githubcopilot.com"


class CopilotTokenManager(BaseTokenManager[CopilotAuthState]):
    """Manage GitHub Copilot OAuth tokens."""

    _LEGACY_STORAGE_KEY = "copilot"

    def __init__(self, auth_file: Path | None = None):
        super().__init__(auth_file)

    @property
    def storage_key(self) -> str:
        return "github-copilot"

    def load(self) -> CopilotAuthState | None:
        state = super().load()
        if state is not None:
            return state

        store = self._load_store()
        legacy_data = store.get(self._LEGACY_STORAGE_KEY)
        if not isinstance(legacy_data, dict):
            return None
        legacy_payload = cast(dict[str, Any], legacy_data)

        try:
            migrated = self._create_state(legacy_payload)
        except ValueError:
            return None

        store[self.storage_key] = migrated.model_dump(mode="json")
        store.pop(self._LEGACY_STORAGE_KEY, None)
        self._save_store(store)
        self._state = migrated
        return migrated

    def delete(self) -> None:
        store = self._load_store()
        store.pop(self.storage_key, None)
        store.pop(self._LEGACY_STORAGE_KEY, None)

        if len(store) == 0:
            if self.auth_file.exists():
                self.auth_file.unlink()
        else:
            self._save_store(store)

        self._state = None

    def _create_state(self, data: dict[str, Any]) -> CopilotAuthState:
        return CopilotAuthState.model_validate(data)
