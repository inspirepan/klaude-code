"""Token storage for xAI authentication."""

from typing import Any

from klaude_code.auth.base import BaseAuthState, BaseTokenManager


class XaiAuthState(BaseAuthState):
    """Stored authentication state for xAI."""


class XaiTokenManager(BaseTokenManager[XaiAuthState]):
    """Manage the single xAI OAuth account."""

    @property
    def storage_key(self) -> str:
        return "xai"

    def _create_state(self, data: dict[str, Any]) -> XaiAuthState:
        return XaiAuthState.model_validate(data)
