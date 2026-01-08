"""Exceptions for Codex authentication."""


class CodexAuthError(Exception):
    """Base exception for Codex authentication errors."""


class CodexNotLoggedInError(CodexAuthError):
    """User has not logged in to Codex."""


class CodexTokenExpiredError(CodexAuthError):
    """Token expired and refresh failed."""


class CodexOAuthError(CodexAuthError):
    """OAuth flow failed."""


class CodexUnsupportedModelError(CodexAuthError):
    """Model is not supported by codex_oauth protocol."""
