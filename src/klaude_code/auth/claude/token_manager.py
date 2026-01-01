"""Token storage and management for Claude (Anthropic OAuth) authentication."""

from pathlib import Path
from typing import Any

from klaude_code.auth.base import BaseAuthState, BaseTokenManager


class ClaudeAuthState(BaseAuthState):
    """Stored authentication state for Claude OAuth."""

    pass


class ClaudeTokenManager(BaseTokenManager[ClaudeAuthState]):
    """Manage Claude OAuth tokens."""

    def __init__(self, auth_file: Path | None = None):
        super().__init__(auth_file)

    @property
    def storage_key(self) -> str:
        return "claude"

    def _create_state(self, data: dict[str, Any]) -> ClaudeAuthState:
        return ClaudeAuthState.model_validate(data)
