"""OAuth device flow for GitHub Copilot authentication."""

import base64
import re
import time
from collections.abc import Callable
from urllib.parse import urlparse

import httpx

from klaude_code.auth.copilot.exceptions import CopilotNotLoggedInError, CopilotOAuthError, CopilotTokenExpiredError
from klaude_code.auth.copilot.token_manager import CopilotAuthState, CopilotTokenManager


def _decode_base64(value: str) -> str:
    return base64.b64decode(value).decode()


# GitHub Copilot OAuth app client id
CLIENT_ID = _decode_base64("SXYxLmI1MDdhMDhjODdlY2ZlOTg=")

COPILOT_STATIC_HEADERS = {
    "User-Agent": "GitHubCopilotChat/0.35.0",
    "Editor-Version": "vscode/1.107.0",
    "Editor-Plugin-Version": "copilot-chat/0.35.0",
    "Copilot-Integration-Id": "vscode-chat",
}


def normalize_domain(input_value: str) -> str | None:
    """Normalize a GitHub domain or URL into hostname."""
    trimmed = input_value.strip()
    if not trimmed:
        return None
    try:
        raw = trimmed if "://" in trimmed else f"https://{trimmed}"
        return urlparse(raw).hostname
    except ValueError:
        return None


def _urls(domain: str) -> tuple[str, str, str]:
    device_code_url = f"https://{domain}/login/device/code"
    access_token_url = f"https://{domain}/login/oauth/access_token"
    copilot_token_url = f"https://api.{domain}/copilot_internal/v2/token"
    return device_code_url, access_token_url, copilot_token_url


def _base_url_from_copilot_token(token: str) -> str | None:
    match = re.search(r"proxy-ep=([^;]+)", token)
    if not match:
        return None
    proxy_host = match.group(1)
    api_host = proxy_host.replace("proxy.", "api.", 1)
    return f"https://{api_host}"


def get_copilot_base_url(token: str, enterprise_domain: str | None) -> str:
    from_token = _base_url_from_copilot_token(token)
    if from_token:
        return from_token
    if enterprise_domain:
        return f"https://copilot-api.{enterprise_domain}"
    return "https://api.individual.githubcopilot.com"


class CopilotOAuth:
    """Handle OAuth device flow for GitHub Copilot authentication."""

    def __init__(self, token_manager: CopilotTokenManager | None = None):
        self.token_manager = token_manager or CopilotTokenManager()

    def _start_device_flow(self, domain: str) -> tuple[str, str, str, int, int]:
        device_code_url, _, _ = _urls(domain)
        payload = {"client_id": CLIENT_ID, "scope": "read:user"}
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": COPILOT_STATIC_HEADERS["User-Agent"],
        }

        with httpx.Client() as client:
            response = client.post(device_code_url, json=payload, headers=headers)

        if response.status_code != 200:
            raise CopilotOAuthError(f"Device code request failed: {response.text}")

        data = response.json()
        try:
            device_code = str(data["device_code"])
            user_code = str(data["user_code"])
            verification_uri = str(data["verification_uri"])
            interval = int(data["interval"])
            expires_in = int(data["expires_in"])
        except (KeyError, TypeError, ValueError) as e:
            raise CopilotOAuthError("Invalid device code response") from e

        return device_code, user_code, verification_uri, interval, expires_in

    def _poll_for_github_access_token(
        self,
        *,
        domain: str,
        device_code: str,
        interval_seconds: int,
        expires_in_seconds: int,
    ) -> str:
        _, access_token_url, _ = _urls(domain)
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": COPILOT_STATIC_HEADERS["User-Agent"],
        }

        deadline = time.time() + expires_in_seconds
        interval = max(1, interval_seconds)

        while time.time() < deadline:
            payload = {
                "client_id": CLIENT_ID,
                "device_code": device_code,
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            }
            with httpx.Client() as client:
                response = client.post(access_token_url, json=payload, headers=headers)

            if response.status_code != 200:
                raise CopilotOAuthError(f"Device flow poll failed: {response.text}")

            data = response.json()
            access_token = data.get("access_token")
            if isinstance(access_token, str) and access_token:
                return access_token

            error = data.get("error")
            if error == "authorization_pending":
                time.sleep(interval)
                continue
            if error == "slow_down":
                interval += 5
                time.sleep(interval)
                continue
            raise CopilotOAuthError(f"Device flow failed: {error}")

        raise CopilotOAuthError("Device flow timed out")

    def _refresh_copilot_token(self, github_access_token: str, enterprise_domain: str | None) -> CopilotAuthState:
        domain = enterprise_domain or "github.com"
        _, _, copilot_token_url = _urls(domain)

        with httpx.Client() as client:
            response = client.get(
                copilot_token_url,
                headers={
                    "Accept": "application/json",
                    "Authorization": f"Bearer {github_access_token}",
                    **COPILOT_STATIC_HEADERS,
                },
            )

        if response.status_code != 200:
            raise CopilotTokenExpiredError(f"Copilot token refresh failed: {response.text}")

        data = response.json()
        token = data.get("token")
        expires_at = data.get("expires_at")
        if not isinstance(token, str) or not isinstance(expires_at, int):
            raise CopilotTokenExpiredError("Invalid Copilot token response")

        # Refresh 5 minutes before upstream expiry.
        local_expires_at = expires_at - 300
        base_url = get_copilot_base_url(token, enterprise_domain)

        return CopilotAuthState(
            access_token=token,
            refresh_token=github_access_token,
            expires_at=local_expires_at,
            enterprise_domain=enterprise_domain,
            copilot_base_url=base_url,
        )

    def login(
        self,
        *,
        enterprise_input: str,
        on_auth: Callable[[str, str], None],
        on_progress: Callable[[str], None] | None = None,
    ) -> CopilotAuthState:
        """Run complete OAuth device flow for GitHub Copilot."""
        enterprise_domain = normalize_domain(enterprise_input)
        if enterprise_input.strip() and enterprise_domain is None:
            raise CopilotOAuthError("Invalid GitHub Enterprise URL/domain")

        domain = enterprise_domain or "github.com"
        device_code, user_code, verification_uri, interval, expires_in = self._start_device_flow(domain)

        on_auth(verification_uri, user_code)
        github_access_token = self._poll_for_github_access_token(
            domain=domain,
            device_code=device_code,
            interval_seconds=interval,
            expires_in_seconds=expires_in,
        )

        if on_progress:
            on_progress("Fetching Copilot access token...")

        auth_state = self._refresh_copilot_token(github_access_token, enterprise_domain)
        self.token_manager.save(auth_state)
        return auth_state

    def refresh(self) -> CopilotAuthState:
        """Refresh Copilot access token using stored GitHub access token."""

        def do_refresh(current_state: CopilotAuthState) -> CopilotAuthState:
            return self._refresh_copilot_token(current_state.refresh_token, current_state.enterprise_domain)

        try:
            return self.token_manager.refresh_with_lock(do_refresh)
        except ValueError as e:
            raise CopilotNotLoggedInError(str(e)) from e

    def ensure_valid_token(self) -> tuple[str, str]:
        """Ensure we have a valid Copilot token and return (token, base_url)."""
        state = self.token_manager.get_state()
        if state is None:
            raise CopilotNotLoggedInError("Not logged in to Copilot. Run 'klaude login copilot' first.")

        if state.is_expired():
            state = self.refresh()

        return state.access_token, state.copilot_base_url
