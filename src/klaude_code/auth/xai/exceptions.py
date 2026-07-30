"""Exceptions for xAI OAuth."""


class XaiOAuthError(Exception):
    """Raised when the xAI OAuth flow fails."""


class XaiNotLoggedInError(XaiOAuthError):
    """Raised when xAI OAuth credentials are unavailable."""


class XaiTokenExpiredError(XaiOAuthError):
    """Raised when xAI OAuth token refresh fails."""
