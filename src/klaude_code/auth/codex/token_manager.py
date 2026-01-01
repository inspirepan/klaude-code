"""Token storage and management for Codex authentication."""

from pathlib import Path
from typing import Any

from klaude_code.auth.base import BaseAuthState, BaseTokenManager


class CodexAuthState(BaseAuthState):
    """Stored authentication state for Codex."""

    account_id: str


class CodexTokenManager(BaseTokenManager[CodexAuthState]):
    """Manage Codex OAuth tokens."""

    def __init__(self, auth_file: Path | None = None):
        super().__init__(auth_file)

    @property
    def storage_key(self) -> str:
        return "codex"

    def _create_state(self, data: dict[str, Any]) -> CodexAuthState:
        return CodexAuthState.model_validate(data)

    def get_access_token(self) -> str:
        """Get access token, raising if not logged in."""
        state = self.get_state()
        if state is None:
            from klaude_code.auth.codex.exceptions import CodexNotLoggedInError

            raise CodexNotLoggedInError("Not logged in to Codex. Run 'klaude login codex' first.")
        return state.access_token

    def get_account_id(self) -> str:
        """Get account ID, raising if not logged in."""
        state = self.get_state()
        if state is None:
            from klaude_code.auth.codex.exceptions import CodexNotLoggedInError

            raise CodexNotLoggedInError("Not logged in to Codex. Run 'klaude login codex' first.")
        return state.account_id
