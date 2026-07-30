"""Device Code OAuth flow for xAI."""

import time
import webbrowser
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urlparse

import httpx

from klaude_code.auth.xai.exceptions import XaiNotLoggedInError, XaiOAuthError, XaiTokenExpiredError
from klaude_code.auth.xai.token_manager import XaiAuthState, XaiTokenManager

CLIENT_ID = "b1a00492-073a-47ea-816f-4c329264a828"
DEVICE_CODE_URL = "https://auth.x.ai/oauth2/device/code"
TOKEN_URL = "https://auth.x.ai/oauth2/token"
SCOPE = "openid profile email offline_access grok-cli:access api:access"
REFERRER = "pi"
HTTP_TIMEOUT_SECONDS = 30

type PollResult = XaiAuthState | Literal["pending"] | tuple[Literal["slow_down"], int | None]


@dataclass(frozen=True)
class XaiDeviceCode:
    """Details that the user needs to authorize a device."""

    device_code: str
    user_code: str
    verification_uri: str
    verification_uri_complete: str | None
    expires_in: int
    interval: int

    @property
    def verification_url(self) -> str:
        """Return the best URL to open in a browser."""
        return self.verification_uri_complete or self.verification_uri


def _required_string(data: dict[str, Any], field: str) -> str:
    value = data.get(field)
    if not isinstance(value, str) or not value:
        raise XaiOAuthError(f"Invalid OAuth response: missing {field}")
    return value


def _positive_int(data: dict[str, Any], field: str, default: int) -> int:
    value = data.get(field, default)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise XaiOAuthError(f"Invalid OAuth response: invalid {field}")
    return value


def _validate_https_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc:
        raise XaiOAuthError("Invalid OAuth response: verification URI must use HTTPS")
    return value


class XaiOAuth:
    """Handle xAI Device Code OAuth and token refresh."""

    def __init__(self, token_manager: XaiTokenManager | None = None):
        self.token_manager = token_manager or XaiTokenManager()

    def login(self, notifier: Callable[[XaiDeviceCode], None] | None = None) -> XaiAuthState:
        """Request a device code, wait for authorization, and save the token."""
        device = self._request_device_code()
        if notifier:
            notifier(device)
        webbrowser.open(device.verification_url)

        deadline = time.monotonic() + device.expires_in
        interval = device.interval
        while True:
            time.sleep(interval)
            if time.monotonic() >= deadline:
                raise XaiOAuthError("xAI authorization timed out")
            result = self._poll_token(device.device_code)
            if isinstance(result, XaiAuthState):
                self.token_manager.save(result)
                return result
            if isinstance(result, tuple):
                _, server_interval = result
                interval = max(interval + 5, server_interval or 0)

    def _request_device_code(self) -> XaiDeviceCode:
        data = {"client_id": CLIENT_ID, "scope": SCOPE, "referrer": REFERRER}
        with httpx.Client(timeout=HTTP_TIMEOUT_SECONDS) as client:
            response = client.post(DEVICE_CODE_URL, data=data)
        if response.status_code != 200:
            raise XaiOAuthError("xAI device authorization request failed")
        payload = _response_data(response)
        verification_uri = _validate_https_url(_required_string(payload, "verification_uri"))
        complete = payload.get("verification_uri_complete")
        if complete is not None:
            if not isinstance(complete, str) or not complete:
                raise XaiOAuthError("Invalid OAuth response: invalid verification_uri_complete")
            complete = _validate_https_url(complete)
        return XaiDeviceCode(
            device_code=_required_string(payload, "device_code"),
            user_code=_required_string(payload, "user_code"),
            verification_uri=verification_uri,
            verification_uri_complete=complete,
            expires_in=_positive_int(payload, "expires_in", 300),
            interval=_positive_int(payload, "interval", 5),
        )

    def _poll_token(self, device_code: str) -> PollResult:
        data = {
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            "device_code": device_code,
            "client_id": CLIENT_ID,
        }
        with httpx.Client(timeout=HTTP_TIMEOUT_SECONDS) as client:
            response = client.post(TOKEN_URL, data=data)
        payload = _response_data(response)
        if response.status_code == 200:
            return _token_state(payload)
        error = payload.get("error")
        if error == "authorization_pending":
            return "pending"
        if error == "slow_down":
            raw_interval = payload.get("interval")
            server_interval = (
                raw_interval
                if isinstance(raw_interval, int) and not isinstance(raw_interval, bool) and raw_interval > 0
                else None
            )
            return "slow_down", server_interval
        if error in {"access_denied", "authorization_denied"}:
            raise XaiOAuthError("xAI authorization was denied")
        if error == "expired_token":
            raise XaiOAuthError("xAI device code expired")
        raise XaiOAuthError("xAI token request failed")

    def refresh(self) -> XaiAuthState:
        """Refresh the access token while holding the shared auth lock."""

        def do_refresh(current_state: XaiAuthState) -> XaiAuthState:
            data = {"grant_type": "refresh_token", "client_id": CLIENT_ID, "refresh_token": current_state.refresh_token}
            with httpx.Client(timeout=HTTP_TIMEOUT_SECONDS) as client:
                response = client.post(TOKEN_URL, data=data)
            if response.status_code != 200:
                raise XaiTokenExpiredError("xAI token refresh failed")
            payload = _response_data(response)
            return _token_state(payload, refresh_token=current_state.refresh_token)

        try:
            return self.token_manager.refresh_with_lock(do_refresh)
        except ValueError as error:
            raise XaiNotLoggedInError(str(error)) from error

    def ensure_valid_token(self) -> str:
        """Return a valid access token, refreshing it when necessary."""
        state = self.token_manager.get_state()
        if state is None:
            raise XaiNotLoggedInError("Not logged in to xAI. Run 'klaude auth login xai' first.")
        if state.is_expired():
            state = self.refresh()
        return state.access_token


def _response_data(response: httpx.Response) -> dict[str, Any]:
    try:
        data = response.json()
    except ValueError as error:
        raise XaiOAuthError("Invalid OAuth response") from error
    if not isinstance(data, dict):
        raise XaiOAuthError("Invalid OAuth response")
    return data


def _token_state(data: dict[str, Any], refresh_token: str | None = None) -> XaiAuthState:
    token = data.get("refresh_token", refresh_token)
    if not isinstance(token, str) or not token:
        raise XaiOAuthError("Invalid OAuth response: missing refresh_token")
    return XaiAuthState(
        access_token=_required_string(data, "access_token"),
        refresh_token=token,
        expires_at=int(time.time()) + _positive_int(data, "expires_in", 3600),
    )
