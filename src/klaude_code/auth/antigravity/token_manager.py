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

    def get_access_token(self) -> str:
        """Get access token, raising if not logged in."""
        state = self.get_state()
        if state is None:
            from klaude_code.auth.antigravity.exceptions import AntigravityNotLoggedInError

            raise AntigravityNotLoggedInError("Not logged in to Antigravity. Run 'klaude login antigravity' first.")
        return state.access_token

    def get_project_id(self) -> str:
        """Get project ID, raising if not logged in."""
        state = self.get_state()
        if state is None:
            from klaude_code.auth.antigravity.exceptions import AntigravityNotLoggedInError

            raise AntigravityNotLoggedInError("Not logged in to Antigravity. Run 'klaude login antigravity' first.")
        return state.project_id
