"""OAuth PKCE flow for Codex authentication."""

import base64
import hashlib
import secrets
import shlex
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
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
CALLBACK_PATH = "/auth/callback"
CALLBACK_WAIT_SECONDS = 300
# A peer that opens the callback port and sends nothing (browser preconnect
# sockets, stale tabs, port probes) must not stall the single-threaded accept
# loop, so each accepted connection gets its own read deadline.
CALLBACK_READ_TIMEOUT_SECONDS = 10
# Connect budgets per token-request attempt, measured here against
# auth.openai.com through a local proxy: a warm TLS handshake takes 0.2s, while a
# cold one can exceed a minute because the proxy has to bring its tunnel up
# first. An attempt the budget cuts off still triggers that work, so short
# attempts usually turn a cold start into a fast retry; the patient final attempt
# keeps a merely slow handshake from failing.
TOKEN_REQUEST_CONNECT_TIMEOUTS = (5.0, 5.0, 30.0)
TOKEN_REQUEST_READ_TIMEOUT_SECONDS = 30.0
_CONNECT_ERRORS = (httpx.ConnectError, httpx.ConnectTimeout)


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
        "originator": "pi",
    }
    return f"{AUTHORIZE_URL}?{urlencode(params)}"


def _post_token_once(data: dict[str, str], connect_timeout: float) -> httpx.Response:
    timeout = httpx.Timeout(TOKEN_REQUEST_READ_TIMEOUT_SECONDS, connect=connect_timeout)
    with httpx.Client(timeout=timeout) as client:
        return client.post(TOKEN_URL, data=data)


def post_token_request(data: dict[str, str]) -> httpx.Response:
    """POST to the token endpoint, retrying a connection that never opened.

    Only connect failures are retried: they sent no request bytes, so a retry
    cannot consume the single-use authorization code.
    """
    impatient_budgets = TOKEN_REQUEST_CONNECT_TIMEOUTS[:-1]
    patient_budget = TOKEN_REQUEST_CONNECT_TIMEOUTS[-1]
    for connect_timeout in impatient_budgets:
        try:
            return _post_token_once(data, connect_timeout)
        except _CONNECT_ERRORS:
            continue
    return _post_token_once(data, patient_budget)


class OAuthCallbackHandler(BaseHTTPRequestHandler):
    """HTTP request handler for OAuth callback."""

    timeout = CALLBACK_READ_TIMEOUT_SECONDS
    code: str | None = None
    state: str | None = None
    error: str | None = None
    resolved: bool = False

    def log_message(self, format: str, *args: Any) -> None:
        """Suppress HTTP server logs."""
        pass

    def do_GET(self) -> None:
        """Handle GET request from OAuth callback."""
        parsed = urlparse(self.path)

        # Anything but the redirect target is noise (favicon, a stale tab) and
        # must leave the wait running.
        if parsed.path != CALLBACK_PATH:
            self.send_error(404)
            return

        params = parse_qs(parsed.query)

        OAuthCallbackHandler.code = params.get("code", [None])[0]
        OAuthCallbackHandler.state = params.get("state", [None])[0]
        OAuthCallbackHandler.error = params.get("error", [None])[0]
        OAuthCallbackHandler.resolved = True

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

    def login(self, account_name: str | None = None, *, set_active: bool = True) -> CodexAuthState:
        """Run the complete OAuth login flow."""
        # Generate PKCE parameters
        verifier = generate_code_verifier()
        challenge = generate_code_challenge(verifier)
        state = secrets.token_urlsafe(32)

        # Build authorization URL
        auth_url = build_authorize_url(challenge, state)

        OAuthCallbackHandler.code = None
        OAuthCallbackHandler.state = None
        OAuthCallbackHandler.error = None
        OAuthCallbackHandler.resolved = False

        # Bind before opening the browser so the redirect cannot miss the port.
        server = HTTPServer(("localhost", REDIRECT_PORT), OAuthCallbackHandler)
        try:
            webbrowser.open(auth_url)
            self._wait_for_callback(server)
        finally:
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

        # Save tokens, then report the state as stored: the manager resolves the
        # final account name and timestamps.
        self.token_manager.save(auth_state, account_name=account_name, set_active=set_active)
        saved_state = self.token_manager.get_state()
        assert saved_state is not None, "save() caches the state it wrote"
        return saved_state

    def _wait_for_callback(self, server: HTTPServer) -> None:
        """Serve callback requests until the redirect carrying the code arrives."""
        deadline = time.monotonic() + CALLBACK_WAIT_SECONDS
        while not OAuthCallbackHandler.resolved:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            server.timeout = remaining
            server.handle_request()

    def _exchange_code(self, code: str, verifier: str) -> CodexAuthState:
        """Exchange authorization code for tokens."""
        data = {
            "grant_type": "authorization_code",
            "client_id": CLIENT_ID,
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "code_verifier": verifier,
        }

        response = post_token_request(data)

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
        """Refresh the access token using refresh token with file locking.

        Uses file locking to prevent multiple instances from refreshing simultaneously.
        If another instance has already refreshed, returns the updated state.
        """

        def do_refresh(current_state: CodexAuthState) -> CodexAuthState:
            data = {
                "grant_type": "refresh_token",
                "client_id": CLIENT_ID,
                "refresh_token": current_state.refresh_token,
            }

            response = post_token_request(data)

            if response.status_code != 200:
                from klaude_code.auth.codex.exceptions import CodexTokenExpiredError

                error_message = f"Token refresh failed: {response.text}"
                if response.status_code in (400, 401):
                    quoted_name = shlex.quote(current_state.name)
                    error_message += (
                        f"\nCodex session for account '{current_state.name}' is no longer valid."
                        f" Log in again with '/login codex {quoted_name}'"
                        f" or 'klaude auth login codex --name {quoted_name}'."
                    )
                raise CodexTokenExpiredError(error_message)

            tokens = response.json()
            access_token = tokens["access_token"]
            refresh_token = tokens.get("refresh_token", current_state.refresh_token)
            expires_in = tokens.get("expires_in", 3600)

            account_id = extract_account_id(access_token)

            return current_state.model_copy(
                update={
                    "access_token": access_token,
                    "refresh_token": refresh_token,
                    "expires_at": int(time.time()) + expires_in,
                    "account_id": account_id,
                }
            )

        try:
            return self.token_manager.refresh_with_lock(do_refresh)
        except ValueError as e:
            from klaude_code.auth.codex.exceptions import CodexNotLoggedInError

            raise CodexNotLoggedInError(str(e)) from e

    def ensure_valid_token(self) -> str:
        """Ensure we have a valid access token, refreshing if needed."""
        state = self.token_manager.get_state()
        if state is None:
            from klaude_code.auth.codex.exceptions import CodexNotLoggedInError

            raise CodexNotLoggedInError("Not logged in to Codex. Run 'klaude auth login codex' first.")

        if state.is_expired():
            state = self.refresh()

        return state.access_token
