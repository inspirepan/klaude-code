"""Exceptions for Claude OAuth authentication."""


class ClaudeAuthError(Exception):
    """Base class for Claude auth errors."""


class ClaudeNotLoggedInError(ClaudeAuthError):
    """Raised when no valid Claude OAuth session is available."""
