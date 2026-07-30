"""Token storage for xAI authentication."""

from typing import Any

from filelock import FileLock

from klaude_code.auth.base import LOCK_TIMEOUT_SECONDS, BaseAuthState, BaseTokenManager


class XaiAuthState(BaseAuthState):
    """Stored authentication state for xAI."""


class XaiTokenManager(BaseTokenManager[XaiAuthState]):
    """Manage the single xAI OAuth account."""

    @property
    def storage_key(self) -> str:
        return "xai"

    def _create_state(self, data: dict[str, Any]) -> XaiAuthState:
        return XaiAuthState.model_validate(data)

    def delete(self) -> None:
        """Delete xAI tokens after any in-flight refresh finishes."""
        with FileLock(self._get_lock_file(), timeout=LOCK_TIMEOUT_SECONDS):
            super().delete()
