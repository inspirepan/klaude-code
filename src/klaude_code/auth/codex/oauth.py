"""OAuth PKCE flow for Codex authentication."""

import base64
import hashlib
import secrets
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

from klaude_code.auth.codex.exceptions import CodexOAuthError
from klaude_code.auth.codex.jwt_utils import extract_account_id
from klaude_code.auth.codex.token_manager import CodexAuthState, CodexTokenManager

# OAuth configuration
CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
AUTHORIZE_URL = "https://auth.openai.com/oauth/authorize"
TOKEN_URL = "https://auth.openai.com/oauth/token"
REDIRECT_URI = "http://localhost:1455/auth/callback"
REDIRECT_PORT = 1455
SCOPE = "openid profile email offline_access"


def generate_code_verifier() -> str:
    """Generate a random code verifier for PKCE."""
    return secrets.token_urlsafe(64)[:128]


def generate_code_challenge(verifier: str) -> str:
    """Generate code challenge from verifier using S256 method."""
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def build_authorize_url(code_challenge: str, state: str) -> str:
    """Build the authorization URL with all required parameters."""
    params = {
        "response_type": "code",
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPE,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "state": state,
        "id_token_add_organizations": "true",
        "codex_cli_simplified_flow": "true",
        "originator": "codex_cli_rs",
    }
    return f"{AUTHORIZE_URL}?{urlencode(params)}"


class OAuthCallbackHandler(BaseHTTPRequestHandler):
    """HTTP request handler for OAuth callback."""

    code: str | None = None
    state: str | None = None
    error: str | None = None

    def log_message(self, format: str, *args: Any) -> None:
        """Suppress HTTP server logs."""
        pass

    def do_GET(self) -> None:
        """Handle GET request from OAuth callback."""
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        OAuthCallbackHandler.code = params.get("code", [None])[0]
        OAuthCallbackHandler.state = params.get("state", [None])[0]
        OAuthCallbackHandler.error = params.get("error", [None])[0]

        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()

        if OAuthCallbackHandler.error:
            html = f"""
            <html><body style="font-family: sans-serif; text-align: center; padding: 50px;">
            <h1>Authentication Failed</h1>
            <p>Error: {OAuthCallbackHandler.error}</p>
            <p>Please close this window and try again.</p>
            </body></html>
            """
        else:
            html = """
            <html><body style="font-family: sans-serif; text-align: center; padding: 50px;">
            <h1>Authentication Successful!</h1>
            <p>You can close this window now.</p>
            <script>setTimeout(function() { window.close(); }, 2000);</script>
            </body></html>
            """
        self.wfile.write(html.encode())


class CodexOAuth:
    """Handle OAuth PKCE flow for Codex authentication."""

    def __init__(self, token_manager: CodexTokenManager | None = None):
        self.token_manager = token_manager or CodexTokenManager()

    def login(self) -> CodexAuthState:
        """Run the complete OAuth login flow."""
        # Generate PKCE parameters
        verifier = generate_code_verifier()
        challenge = generate_code_challenge(verifier)
        state = secrets.token_urlsafe(32)

        # Build authorization URL
        auth_url = build_authorize_url(challenge, state)

        # Start callback server
        OAuthCallbackHandler.code = None
        OAuthCallbackHandler.state = None
        OAuthCallbackHandler.error = None

        server = HTTPServer(("localhost", REDIRECT_PORT), OAuthCallbackHandler)
        server_thread = Thread(target=server.handle_request)
        server_thread.start()

        # Open browser for user to authenticate
        webbrowser.open(auth_url)

        # Wait for callback
        server_thread.join(timeout=300)  # 5 minute timeout
        server.server_close()

        # Check for errors
        if OAuthCallbackHandler.error:
            raise CodexOAuthError(f"OAuth error: {OAuthCallbackHandler.error}")

        if not OAuthCallbackHandler.code:
            raise CodexOAuthError("No authorization code received")

        if OAuthCallbackHandler.state is None or OAuthCallbackHandler.state != state:
            raise CodexOAuthError("OAuth state mismatch")

        # Exchange code for tokens
        auth_state = self._exchange_code(OAuthCallbackHandler.code, verifier)

        # Save tokens
        self.token_manager.save(auth_state)

        return auth_state

    def _exchange_code(self, code: str, verifier: str) -> CodexAuthState:
        """Exchange authorization code for tokens."""
        data = {
            "grant_type": "authorization_code",
            "client_id": CLIENT_ID,
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "code_verifier": verifier,
        }

        with httpx.Client() as client:
            response = client.post(TOKEN_URL, data=data)

        if response.status_code != 200:
            raise CodexOAuthError(f"Token exchange failed: {response.text}")

        tokens = response.json()
        access_token = tokens["access_token"]
        refresh_token = tokens["refresh_token"]
        expires_in = tokens.get("expires_in", 3600)

        account_id = extract_account_id(access_token)

        return CodexAuthState(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=int(time.time()) + expires_in,
            account_id=account_id,
        )

    def refresh(self) -> CodexAuthState:
        """Refresh the access token using refresh token."""
        state = self.token_manager.get_state()
        if state is None:
            from klaude_code.auth.codex.exceptions import CodexNotLoggedInError

            raise CodexNotLoggedInError("Not logged in to Codex. Run 'klaude login codex' first.")

        data = {
            "grant_type": "refresh_token",
            "client_id": CLIENT_ID,
            "refresh_token": state.refresh_token,
        }

        with httpx.Client() as client:
            response = client.post(TOKEN_URL, data=data)

        if response.status_code != 200:
            from klaude_code.auth.codex.exceptions import CodexTokenExpiredError

            raise CodexTokenExpiredError(f"Token refresh failed: {response.text}")

        tokens = response.json()
        access_token = tokens["access_token"]
        refresh_token = tokens.get("refresh_token", state.refresh_token)
        expires_in = tokens.get("expires_in", 3600)

        account_id = extract_account_id(access_token)

        new_state = CodexAuthState(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=int(time.time()) + expires_in,
            account_id=account_id,
        )

        self.token_manager.save(new_state)
        return new_state

    def ensure_valid_token(self) -> str:
        """Ensure we have a valid access token, refreshing if needed."""
        state = self.token_manager.get_state()
        if state is None:
            from klaude_code.auth.codex.exceptions import CodexNotLoggedInError

            raise CodexNotLoggedInError("Not logged in to Codex. Run 'klaude login codex' first.")

        if state.is_expired():
            state = self.refresh()

        return state.access_token
