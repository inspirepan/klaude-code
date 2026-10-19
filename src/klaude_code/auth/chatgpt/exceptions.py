"""Exceptions for Sign in with ChatGPT authentication."""


class ChatGPTAuthError(Exception):
    """Base exception for ChatGPT authentication errors."""


class ChatGPTNotLoggedInError(ChatGPTAuthError):
    """User has not signed in with ChatGPT."""


class ChatGPTTokenExpiredError(ChatGPTAuthError):
    """Token expired and refresh failed."""


class ChatGPTOAuthError(ChatGPTAuthError):
    """OAuth flow failed."""
