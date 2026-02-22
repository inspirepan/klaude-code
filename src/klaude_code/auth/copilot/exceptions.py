"""Exceptions for GitHub Copilot authentication."""


class CopilotAuthError(Exception):
    """Base exception for Copilot authentication errors."""


class CopilotNotLoggedInError(CopilotAuthError):
    """User has not logged in to Copilot."""


class CopilotTokenExpiredError(CopilotAuthError):
    """Token expired and refresh failed."""


class CopilotOAuthError(CopilotAuthError):
    """OAuth flow failed."""
