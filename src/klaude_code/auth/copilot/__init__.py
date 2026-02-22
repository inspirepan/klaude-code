"""GitHub Copilot authentication helpers."""

from klaude_code.auth.copilot.exceptions import (
    CopilotAuthError,
    CopilotNotLoggedInError,
    CopilotOAuthError,
    CopilotTokenExpiredError,
)
from klaude_code.auth.copilot.oauth import CopilotOAuth
from klaude_code.auth.copilot.token_manager import CopilotAuthState, CopilotTokenManager

__all__ = [
    "CopilotAuthError",
    "CopilotAuthState",
    "CopilotNotLoggedInError",
    "CopilotOAuth",
    "CopilotOAuthError",
    "CopilotTokenExpiredError",
    "CopilotTokenManager",
]
