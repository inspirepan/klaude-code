"""OAuth PKCE flow for Claude (Anthropic OAuth) authentication."""

import base64
import hashlib
import secrets
import time
from collections.abc import Callable

import httpx

from klaude_code.auth.claude.exceptions import ClaudeAuthError, ClaudeNotLoggedInError
from klaude_code.auth.claude.token_manager import ClaudeAuthState, ClaudeTokenManager


def _decode_base64(value: str) -> str:
    return base64.b64decode(value).decode()


# OAuth configuration (Claude Pro/Max)
CLIENT_ID = _decode_base64("OWQxYzI1MGEtZTYxYi00NGQ5LTg4ZWQtNTk0NGQxOTYyZjVl")
AUTHORIZE_URL = "https://claude.ai/oauth/authorize"
TOKEN_URL = "https://console.anthropic.com/v1/oauth/token"
REDIRECT_URI = "https://console.anthropic.com/oauth/code/callback"
SCOPE = "org:create_api_key user:profile user:inference"


def generate_code_verifier() -> str:
    """Generate a random code verifier for PKCE."""
    return secrets.token_urlsafe(64)[:128]


def generate_code_challenge(verifier: str) -> str:
    """Generate code challenge from verifier using S256 method."""
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def build_authorize_url(code_challenge: str, state: str) -> str:
    """Build the authorization URL with all required parameters."""
    # Note: the `code=true` parameter is required for the console callback flow.
    params = {
        "code": "true",
        "client_id": CLIENT_ID,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPE,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "state": state,
    }

    encoded = httpx.QueryParams(params)
    return f"{AUTHORIZE_URL}?{encoded}"


def _parse_user_code(value: str) -> tuple[str, str | None]:
    raw = value.strip()
    if "#" in raw:
        code, state = raw.split("#", 1)
        return code.strip(), state.strip()
    return raw, None


class ClaudeOAuth:
    """Handle OAuth PKCE flow for Claude (Anthropic OAuth) authentication."""

    def __init__(self, token_manager: ClaudeTokenManager | None = None):
        self.token_manager = token_manager or ClaudeTokenManager()

    def login(
        self,
        *,
        on_auth_url: Callable[[str], None],
        on_prompt_code: Callable[[], str],
    ) -> ClaudeAuthState:
        """Run the complete OAuth login flow."""
        verifier = generate_code_verifier()
        challenge = generate_code_challenge(verifier)

        # Some flows require `state` to be echoed back for token exchange.
        state = verifier

        auth_url = build_authorize_url(challenge, state)
        on_auth_url(auth_url)

        raw_user_code = on_prompt_code()
        code, returned_state = _parse_user_code(raw_user_code)
        if not code:
            raise ClaudeAuthError("No authorization code provided")

        exchange_state = returned_state or state
        auth_state = self._exchange_code(code=code, state=exchange_state, verifier=verifier)
        self.token_manager.save(auth_state)
        return auth_state

    def _exchange_code(self, *, code: str, state: str, verifier: str) -> ClaudeAuthState:
        """Exchange authorization code for tokens."""
        payload = {
            "grant_type": "authorization_code",
            "client_id": CLIENT_ID,
            "code": code,
            "state": state,
            "redirect_uri": REDIRECT_URI,
            "code_verifier": verifier,
        }

        with httpx.Client() as client:
            response = client.post(
                TOKEN_URL,
                json=payload,
                headers={"Content-Type": "application/json"},
            )

        if response.status_code != 200:
            raise ClaudeAuthError(f"Token exchange failed: {response.text}")

        tokens = response.json()
        access_token = tokens["access_token"]
        refresh_token = tokens["refresh_token"]
        expires_in = tokens.get("expires_in", 3600)

        return ClaudeAuthState(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=int(time.time()) + int(expires_in),
        )

    def refresh(self) -> ClaudeAuthState:
        """Refresh the access token using refresh token with file locking.

        Uses file locking to prevent multiple instances from refreshing simultaneously.
        If another instance has already refreshed, returns the updated state.
        """

        def do_refresh(current_state: ClaudeAuthState) -> ClaudeAuthState:
            payload = {
                "grant_type": "refresh_token",
                "client_id": CLIENT_ID,
                "refresh_token": current_state.refresh_token,
            }

            with httpx.Client() as client:
                response = client.post(
                    TOKEN_URL,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                )

            if response.status_code != 200:
                raise ClaudeAuthError(f"Token refresh failed: {response.text}")

            tokens = response.json()
            access_token = tokens["access_token"]
            refresh_token = tokens.get("refresh_token", current_state.refresh_token)
            expires_in = tokens.get("expires_in", 3600)

            return ClaudeAuthState(
                access_token=access_token,
                refresh_token=refresh_token,
                expires_at=int(time.time()) + int(expires_in),
            )

        try:
            return self.token_manager.refresh_with_lock(do_refresh)
        except ValueError as e:
            raise ClaudeNotLoggedInError(str(e)) from e

    def ensure_valid_token(self) -> str:
        """Ensure we have a valid access token, refreshing if needed."""
        state = self.token_manager.get_state()
        if state is None:
            raise ClaudeNotLoggedInError("Not logged in to Claude. Run 'klaude login claude' first.")

        if state.is_expired():
            state = self.refresh()

        return state.access_token
