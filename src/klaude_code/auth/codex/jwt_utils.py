"""JWT parsing utilities for Codex authentication."""

import base64
import json
from typing import Any


def decode_jwt_payload(token: str) -> dict[str, Any]:
    """Decode JWT payload without verification.

    Args:
        token: JWT token string

    Returns:
        Decoded payload as a dictionary
    """
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("Invalid JWT format")

    payload = parts[1]
    # Add padding if needed
    padding = 4 - len(payload) % 4
    if padding != 4:
        payload += "=" * padding

    decoded = base64.urlsafe_b64decode(payload)
    return json.loads(decoded)


def extract_account_id(token: str) -> str:
    """Extract ChatGPT account ID from JWT token.

    Args:
        token: JWT access token from OpenAI OAuth

    Returns:
        The chatgpt_account_id from the token claims
    """
    payload = decode_jwt_payload(token)
    auth_claim = payload.get("https://api.openai.com/auth", {})
    account_id = auth_claim.get("chatgpt_account_id")
    if not account_id:
        raise ValueError("chatgpt_account_id not found in token")
    return account_id
