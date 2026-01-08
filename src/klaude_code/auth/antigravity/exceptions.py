"""Exceptions for Antigravity authentication."""


class AntigravityAuthError(Exception):
    """Base exception for Antigravity authentication errors."""


class AntigravityNotLoggedInError(AntigravityAuthError):
    """User has not logged in to Antigravity."""


class AntigravityTokenExpiredError(AntigravityAuthError):
    """Token expired and refresh failed."""


class AntigravityOAuthError(AntigravityAuthError):
    """OAuth flow failed."""
