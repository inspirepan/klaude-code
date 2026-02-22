"""Token storage and management for GitHub Copilot authentication."""

from pathlib import Path
from typing import Any

from klaude_code.auth.base import BaseAuthState, BaseTokenManager


class CopilotAuthState(BaseAuthState):
    """Stored authentication state for GitHub Copilot."""

    enterprise_domain: str | None = None
    copilot_base_url: str = "https://api.individual.githubcopilot.com"


class CopilotTokenManager(BaseTokenManager[CopilotAuthState]):
    """Manage GitHub Copilot OAuth tokens."""

    def __init__(self, auth_file: Path | None = None):
        super().__init__(auth_file)

    @property
    def storage_key(self) -> str:
        return "copilot"

    def _create_state(self, data: dict[str, Any]) -> CopilotAuthState:
        return CopilotAuthState.model_validate(data)
