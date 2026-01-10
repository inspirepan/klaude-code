"""Token storage and management for Antigravity authentication."""

from pathlib import Path
from typing import Any

from klaude_code.auth.base import BaseAuthState, BaseTokenManager


class AntigravityAuthState(BaseAuthState):
    """Stored authentication state for Antigravity."""

    project_id: str
    email: str | None = None


class AntigravityTokenManager(BaseTokenManager[AntigravityAuthState]):
    """Manage Antigravity OAuth tokens."""

    def __init__(self, auth_file: Path | None = None):
        super().__init__(auth_file)

    @property
    def storage_key(self) -> str:
        return "antigravity"

    def _create_state(self, data: dict[str, Any]) -> AntigravityAuthState:
        return AntigravityAuthState.model_validate(data)
