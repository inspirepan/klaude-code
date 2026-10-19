"""OAuth PKCE flow for Sign in with ChatGPT."""

import base64
import hashlib
import html
import secrets
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, cast
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

from klaude_code.auth.chatgpt.exceptions import (
    ChatGPTNotLoggedInError,
    ChatGPTOAuthError,
    ChatGPTTokenExpiredError,
)
from klaude_code.auth.chatgpt.token_manager import ChatGPTAuthState, ChatGPTTokenManager
from klaude_code.const import CHATGPT_API_BASE_URL

# A public client. The first sign-in registers a client with this entrypoint ID
# and OpenAI returns the issued `oaiapp_...` ID in the callback.
DYNAMIC_CLIENT_ID = "dynamic_agent_client"
AGENT_NAME_HINT = "klaude-code"
AUTHORIZE_URL = "https://auth.openai.com/api/accounts/authorize"
TOKEN_URL = "https://auth.openai.com/api/accounts/oauth/token"
RESOURCE = CHATGPT_API_BASE_URL
REDIRECT_URI = "http://127.0.0.1:1455/auth/callback"
REDIRECT_HOST = "127.0.0.1"
REDIRECT_PORT = 1455
CALLBACK_PATH = "/auth/callback"
DIRECT_TOKEN_SCOPE = "chatgpt.tokens.use.direct"
SCOPE = f"openid profile email offline_access resource.invoke {DIRECT_TOKEN_SCOPE}"
CALLBACK_WAIT_SECONDS = 300
# A peer that opens the callback port and sends nothing (browser preconnect
# sockets, stale tabs, port probes) must not stall the single-threaded accept
# loop, so each accepted connection gets its own read deadline.
CALLBACK_READ_TIMEOUT_SECONDS = 10
# Connect budgets per token-request attempt. Only connect failures are retried:
# they sent no request bytes, so a retry cannot consume the single-use code.
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


def build_authorize_url(code_challenge: str, state: str, nonce: str, device_id: str) -> str:
    """Build the authorization URL with all required parameters."""
    params = {
        "response_type": "code",
        "client_id": DYNAMIC_CLIENT_ID,
        "agent_name_hint": AGENT_NAME_HINT,
        "ext_agent_host_id": f"urn:uuid:{device_id}",
        "redirect_uri": REDIRECT_URI,
        "resource": RESOURCE,
        "scope": SCOPE,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "state": state,
        "nonce": nonce,
    }
    return f"{AUTHORIZE_URL}?{urlencode(params)}"


def _post_token_once(data: dict[str, str], connect_timeout: float) -> httpx.Response:
    timeout = httpx.Timeout(TOKEN_REQUEST_READ_TIMEOUT_SECONDS, connect=connect_timeout)
    with httpx.Client(timeout=timeout) as client:
        return client.post(TOKEN_URL, data=data)


def post_token_request(data: dict[str, str]) -> httpx.Response:
    """POST to the token endpoint, retrying a connection that never opened."""
    impatient_budgets = TOKEN_REQUEST_CONNECT_TIMEOUTS[:-1]
    patient_budget = TOKEN_REQUEST_CONNECT_TIMEOUTS[-1]
    for connect_timeout in impatient_budgets:
        try:
            return _post_token_once(data, connect_timeout)
        except _CONNECT_ERRORS:
            continue
    return _post_token_once(data, patient_budget)


class OAuthCallbackHandler(BaseHTTPRequestHandler):
    """HTTP request handler for the OAuth callback."""

    timeout = CALLBACK_READ_TIMEOUT_SECONDS
    code: str | None = None
    state: str | None = None
    client_id: str | None = None
    scope: str | None = None
    error: str | None = None
    resolved: bool = False

    def log_message(self, format: str, *args: Any) -> None:
        """Suppress HTTP server logs."""
        pass

    def do_GET(self) -> None:
        """Handle GET request from the OAuth callback."""
        parsed = urlparse(self.path)

        # Anything but the redirect target is noise (favicon, a stale tab) and
        # must leave the wait running.
        if parsed.path != CALLBACK_PATH:
            self.send_error(404)
            return

        params = parse_qs(parsed.query)

        OAuthCallbackHandler.code = params.get("code", [None])[0]
        OAuthCallbackHandler.state = params.get("state", [None])[0]
        OAuthCallbackHandler.client_id = params.get("client_id", [None])[0]
        OAuthCallbackHandler.scope = params.get("scope", [None])[0]
        OAuthCallbackHandler.error = params.get("error", [None])[0]
        OAuthCallbackHandler.resolved = True

        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()

        if OAuthCallbackHandler.error:
            message = html.escape(OAuthCallbackHandler.error)
            body = f"""
            <html><body style="font-family: sans-serif; text-align: center; padding: 50px;">
            <h1>Authentication Failed</h1>
            <p>Error: {message}</p>
            <p>Please close this window and try again.</p>
            </body></html>
            """
        else:
            body = """
            <html><body style="font-family: sans-serif; text-align: center; padding: 50px;">
            <h1>Authentication Successful!</h1>
            <p>You can close this window now.</p>
            <script>setTimeout(function() { window.close(); }, 2000);</script>
            </body></html>
            """
        self.wfile.write(body.encode())


class ChatGPTOAuth:
    """Handle the Sign in with ChatGPT OAuth flow."""

    def __init__(self, token_manager: ChatGPTTokenManager | None = None):
        self.token_manager = token_manager or ChatGPTTokenManager()

    def login(self) -> ChatGPTAuthState:
        """Run the complete OAuth login flow."""
        verifier = generate_code_verifier()
        challenge = generate_code_challenge(verifier)
        state = secrets.token_urlsafe(32)
        nonce = secrets.token_urlsafe(32)
        device_id = self.token_manager.get_or_create_device_id()
        auth_url = build_authorize_url(challenge, state, nonce, device_id)

        OAuthCallbackHandler.code = None
        OAuthCallbackHandler.state = None
        OAuthCallbackHandler.client_id = None
        OAuthCallbackHandler.scope = None
        OAuthCallbackHandler.error = None
        OAuthCallbackHandler.resolved = False

        # Bind before opening the browser so the redirect cannot miss the port.
        try:
            server = HTTPServer((REDIRECT_HOST, REDIRECT_PORT), OAuthCallbackHandler)
        except OSError as e:
            raise ChatGPTOAuthError(
                f"Port {REDIRECT_PORT} is in use. Cancel any pending login in another session and try again."
            ) from e
        try:
            webbrowser.open(auth_url)
            self._wait_for_callback(server)
        finally:
            server.server_close()

        if OAuthCallbackHandler.error:
            raise ChatGPTOAuthError(f"OAuth error: {OAuthCallbackHandler.error}")

        if not OAuthCallbackHandler.code:
            raise ChatGPTOAuthError("No authorization code received")

        if OAuthCallbackHandler.state is None or OAuthCallbackHandler.state != state:
            raise ChatGPTOAuthError("OAuth state mismatch")

        client_id = (OAuthCallbackHandler.client_id or "").strip()
        if not client_id:
            raise ChatGPTOAuthError("OpenAI did not return a client ID for this registration")

        auth_state = self._exchange_code(OAuthCallbackHandler.code, verifier, client_id)
        self.token_manager.save(auth_state)
        return auth_state

    def _wait_for_callback(self, server: HTTPServer) -> None:
        """Serve callback requests until the redirect carrying the code arrives."""
        deadline = time.monotonic() + CALLBACK_WAIT_SECONDS
        while not OAuthCallbackHandler.resolved:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            server.timeout = remaining
            server.handle_request()

    def _exchange_code(self, code: str, verifier: str, client_id: str) -> ChatGPTAuthState:
        """Exchange the authorization code for tokens."""
        data = {
            "grant_type": "authorization_code",
            "client_id": client_id,
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "code_verifier": verifier,
            "resource": RESOURCE,
        }

        response = post_token_request(data)

        if response.status_code != 200:
            raise ChatGPTOAuthError(f"Token exchange failed: {response.text}")

        return self._state_from_token_response(response.json(), client_id=client_id)

    def refresh(self) -> ChatGPTAuthState:
        """Refresh the access token using the stored refresh token."""

        def do_refresh(current_state: ChatGPTAuthState) -> ChatGPTAuthState:
            data = {
                "grant_type": "refresh_token",
                "client_id": current_state.client_id,
                "refresh_token": current_state.refresh_token,
                "resource": RESOURCE,
            }

            response = post_token_request(data)

            if response.status_code != 200:
                error_message = f"Token refresh failed: {response.text}"
                if response.status_code in (400, 401):
                    error_message += (
                        "\nChatGPT session is no longer valid. Log in again with 'klaude auth login chatgpt'."
                    )
                raise ChatGPTTokenExpiredError(error_message)

            return self._state_from_token_response(
                response.json(),
                client_id=current_state.client_id,
                previous=current_state,
            )

        try:
            return self.token_manager.refresh_with_lock(do_refresh)
        except ValueError as e:
            raise ChatGPTNotLoggedInError(str(e)) from e

    def _state_from_token_response(
        self,
        tokens: object,
        *,
        client_id: str,
        previous: ChatGPTAuthState | None = None,
    ) -> ChatGPTAuthState:
        if not isinstance(tokens, dict):
            raise ChatGPTOAuthError("Token response must be a JSON object")

        data = cast(dict[str, Any], tokens)
        access_token = data.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise ChatGPTOAuthError("Token response is missing access_token")

        refresh_token = data.get("refresh_token")
        if not isinstance(refresh_token, str) or not refresh_token:
            refresh_token = previous.refresh_token if previous else None
        if not refresh_token:
            raise ChatGPTOAuthError("Token response is missing refresh_token")

        expires_in = data.get("expires_in", 3600)
        if not isinstance(expires_in, (int, float)) or expires_in <= 0:
            raise ChatGPTOAuthError("Token response has invalid expires_in")

        scopes = self._parse_scopes(data.get("scope")) or (previous.scopes if previous else [])
        if DIRECT_TOKEN_SCOPE not in scopes:
            raise ChatGPTOAuthError(f"OpenAI OAuth grant did not include {DIRECT_TOKEN_SCOPE}")

        id_token = data.get("id_token")
        if not isinstance(id_token, str) or not id_token:
            id_token = previous.id_token if previous else None

        return ChatGPTAuthState(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=int(time.time()) + int(expires_in),
            client_id=client_id,
            scopes=scopes,
            id_token=id_token,
        )

    @staticmethod
    def _parse_scopes(value: object) -> list[str]:
        if not isinstance(value, str):
            return []
        return value.split()
