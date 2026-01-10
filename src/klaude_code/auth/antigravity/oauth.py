"""OAuth PKCE flow for Antigravity authentication."""

import base64
import json
import secrets
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
from typing import Any, cast
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

from klaude_code.auth.antigravity.exceptions import (
    AntigravityNotLoggedInError,
    AntigravityOAuthError,
    AntigravityTokenExpiredError,
)
from klaude_code.auth.antigravity.pkce import generate_pkce
from klaude_code.auth.antigravity.token_manager import AntigravityAuthState, AntigravityTokenManager

# OAuth configuration (decoded from base64 for compatibility with pi implementation)
CLIENT_ID = base64.b64decode(
    "MTA3MTAwNjA2MDU5MS10bWhzc2luMmgyMWxjcmUyMzV2dG9sb2poNGc0MDNlcC5hcHBzLmdvb2dsZXVzZXJjb250ZW50LmNvbQ=="
).decode()
CLIENT_SECRET = base64.b64decode("R09DU1BYLUs1OEZXUjQ4NkxkTEoxbUxCOHNYQzR6NnFEQWY=").decode()
REDIRECT_URI = "http://localhost:51121/oauth-callback"
REDIRECT_PORT = 51121

# Google OAuth endpoints
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"

# Antigravity requires additional scopes
SCOPES = [
    "https://www.googleapis.com/auth/cloud-platform",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/cclog",
    "https://www.googleapis.com/auth/experimentsandconfigs",
]

# Fallback project ID when discovery fails
DEFAULT_PROJECT_ID = "rising-fact-p41fc"

# Cloud Code Assist endpoint
CLOUDCODE_ENDPOINT = "https://cloudcode-pa.googleapis.com"


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


def _discover_project(access_token: str) -> str:
    """Discover or provision a project for the user."""
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "User-Agent": "google-api-nodejs-client/9.15.1",
        "X-Goog-Api-Client": "google-cloud-sdk vscode_cloudshelleditor/0.1",
        "Client-Metadata": json.dumps(
            {
                "ideType": "IDE_UNSPECIFIED",
                "platform": "PLATFORM_UNSPECIFIED",
                "pluginType": "GEMINI",
            }
        ),
    }

    try:
        with httpx.Client() as client:
            response = client.post(
                f"{CLOUDCODE_ENDPOINT}/v1internal:loadCodeAssist",
                headers=headers,
                json={
                    "metadata": {
                        "ideType": "IDE_UNSPECIFIED",
                        "platform": "PLATFORM_UNSPECIFIED",
                        "pluginType": "GEMINI",
                    },
                },
                timeout=30,
            )

            if response.status_code == 200:
                data: dict[str, Any] = response.json()
                project = data.get("cloudaicompanionProject")
                if isinstance(project, str) and project:
                    return project
                if isinstance(project, dict):
                    project_dict = cast(dict[str, Any], project)
                    project_id = project_dict.get("id")
                    if isinstance(project_id, str) and project_id:
                        return project_id
    except Exception:
        pass

    return DEFAULT_PROJECT_ID


def _get_user_email(access_token: str) -> str | None:
    """Get user email from the access token."""
    try:
        with httpx.Client() as client:
            response = client.get(
                "https://www.googleapis.com/oauth2/v1/userinfo?alt=json",
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=10,
            )
            if response.status_code == 200:
                data = response.json()
                return data.get("email")
    except Exception:
        pass
    return None


class AntigravityOAuth:
    """Handle OAuth PKCE flow for Antigravity authentication."""

    def __init__(self, token_manager: AntigravityTokenManager | None = None):
        self.token_manager = token_manager or AntigravityTokenManager()

    def login(self) -> AntigravityAuthState:
        """Run the complete OAuth login flow."""
        verifier, challenge = generate_pkce()
        state = secrets.token_urlsafe(32)

        # Build authorization URL
        auth_params = {
            "client_id": CLIENT_ID,
            "response_type": "code",
            "redirect_uri": REDIRECT_URI,
            "scope": " ".join(SCOPES),
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": state,
            "access_type": "offline",
            "prompt": "consent",
        }
        auth_url = f"{AUTH_URL}?{urlencode(auth_params)}"

        # Reset callback handler state
        OAuthCallbackHandler.code = None
        OAuthCallbackHandler.state = None
        OAuthCallbackHandler.error = None

        # Start callback server
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
            raise AntigravityOAuthError(f"OAuth error: {OAuthCallbackHandler.error}")

        if not OAuthCallbackHandler.code:
            raise AntigravityOAuthError("No authorization code received")

        if OAuthCallbackHandler.state is None or OAuthCallbackHandler.state != state:
            raise AntigravityOAuthError("OAuth state mismatch")

        # Exchange code for tokens
        auth_state = self._exchange_code(OAuthCallbackHandler.code, verifier)

        # Save tokens
        self.token_manager.save(auth_state)

        return auth_state

    def _exchange_code(self, code: str, verifier: str) -> AntigravityAuthState:
        """Exchange authorization code for tokens."""
        data = {
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": REDIRECT_URI,
            "code_verifier": verifier,
        }

        with httpx.Client() as client:
            response = client.post(TOKEN_URL, data=data, timeout=30)

        if response.status_code != 200:
            raise AntigravityOAuthError(f"Token exchange failed: {response.text}")

        tokens = response.json()
        access_token = tokens["access_token"]
        refresh_token = tokens.get("refresh_token")
        expires_in = tokens.get("expires_in", 3600)

        if not refresh_token:
            raise AntigravityOAuthError("No refresh token received. Please try again.")

        # Get user email
        email = _get_user_email(access_token)

        # Discover project
        project_id = _discover_project(access_token)

        # Calculate expiry time with 5 minute buffer
        expires_at = int(time.time()) + expires_in - 300

        return AntigravityAuthState(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=expires_at,
            project_id=project_id,
            email=email,
        )

    def refresh(self) -> AntigravityAuthState:
        """Refresh the access token using refresh token with file locking.

        Uses file locking to prevent multiple instances from refreshing simultaneously.
        If another instance has already refreshed, returns the updated state.
        """

        def do_refresh(current_state: AntigravityAuthState) -> AntigravityAuthState:
            data = {
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "refresh_token": current_state.refresh_token,
                "grant_type": "refresh_token",
            }

            with httpx.Client() as client:
                response = client.post(TOKEN_URL, data=data, timeout=30)

            if response.status_code != 200:
                raise AntigravityTokenExpiredError(f"Token refresh failed: {response.text}")

            tokens = response.json()
            access_token = tokens["access_token"]
            refresh_token = tokens.get("refresh_token", current_state.refresh_token)
            expires_in = tokens.get("expires_in", 3600)

            # Calculate expiry time with 5 minute buffer
            expires_at = int(time.time()) + expires_in - 300

            return AntigravityAuthState(
                access_token=access_token,
                refresh_token=refresh_token,
                expires_at=expires_at,
                project_id=current_state.project_id,
                email=current_state.email,
            )

        try:
            return self.token_manager.refresh_with_lock(do_refresh)
        except ValueError as e:
            raise AntigravityNotLoggedInError(str(e)) from e

    def ensure_valid_token(self) -> tuple[str, str]:
        """Ensure we have a valid access token, refreshing if needed.

        Returns:
            Tuple of (access_token, project_id).
        """
        state = self.token_manager.get_state()
        if state is None:
            raise AntigravityNotLoggedInError("Not logged in to Antigravity. Run 'klaude login antigravity' first.")

        if state.is_expired():
            state = self.refresh()

        return state.access_token, state.project_id
