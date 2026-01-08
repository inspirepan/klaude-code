"""PKCE utilities for Antigravity OAuth."""

import base64
import hashlib
import secrets


def base64url_encode(data: bytes) -> str:
    """Encode bytes as base64url string without padding."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def generate_pkce() -> tuple[str, str]:
    """Generate PKCE code verifier and challenge.

    Returns:
        Tuple of (verifier, challenge).
    """
    verifier_bytes = secrets.token_bytes(32)
    verifier = base64url_encode(verifier_bytes)

    challenge_hash = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64url_encode(challenge_hash)

    return verifier, challenge
