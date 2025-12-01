"""Token storage and management for Codex authentication."""

import json
import time
from pathlib import Path

from pydantic import BaseModel


class CodexAuthState(BaseModel):
    """Stored authentication state for Codex."""

    access_token: str
    refresh_token: str
    expires_at: int  # Unix timestamp
    account_id: str

    def is_expired(self, buffer_seconds: int = 300) -> bool:
        """Check if token is expired or will expire soon."""
        return time.time() + buffer_seconds >= self.expires_at


CODEX_AUTH_FILE = Path.home() / ".klaude" / "codex-auth.json"


class CodexTokenManager:
    """Manage Codex OAuth tokens."""

    def __init__(self, auth_file: Path | None = None):
        self.auth_file = auth_file or CODEX_AUTH_FILE
        self._state: CodexAuthState | None = None

    def load(self) -> CodexAuthState | None:
        """Load authentication state from file."""
        if not self.auth_file.exists():
            return None

        try:
            data = json.loads(self.auth_file.read_text())
            self._state = CodexAuthState.model_validate(data)
            return self._state
        except (json.JSONDecodeError, ValueError):
            return None

    def save(self, state: CodexAuthState) -> None:
        """Save authentication state to file."""
        self.auth_file.parent.mkdir(parents=True, exist_ok=True)
        self.auth_file.write_text(state.model_dump_json(indent=2))
        self._state = state

    def delete(self) -> None:
        """Delete stored tokens."""
        if self.auth_file.exists():
            self.auth_file.unlink()
        self._state = None

    def is_logged_in(self) -> bool:
        """Check if user is logged in."""
        state = self._state or self.load()
        return state is not None

    def get_state(self) -> CodexAuthState | None:
        """Get current authentication state."""
        if self._state is None:
            self._state = self.load()
        return self._state

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
