"""OAuth provider usage snapshot helpers for human-readable model list output."""

from __future__ import annotations

import datetime
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import cast

import httpx

from klaude_code.auth.claude.oauth import ClaudeOAuth
from klaude_code.auth.claude.token_manager import ClaudeTokenManager
from klaude_code.auth.codex.oauth import CodexOAuth
from klaude_code.auth.codex.token_manager import CodexTokenManager
from klaude_code.auth.copilot.oauth import COPILOT_STATIC_HEADERS
from klaude_code.auth.copilot.token_manager import CopilotTokenManager
from klaude_code.const import ANTHROPIC_BETA_OAUTH, CODEX_USER_AGENT
from klaude_code.protocol.llm_param import LLMClientProtocol


@dataclass(slots=True)
class UsageWindowSnapshot:
    label: str
    used_percent: float
    reset_at_epoch_ms: int | None = None


@dataclass(slots=True)
class OAuthUsageSnapshot:
    protocol: LLMClientProtocol
    windows: list[UsageWindowSnapshot]
    plan: str | None = None
    error: str | None = None


@dataclass(slots=True)
class _OAuthProviderAuth:
    protocol: LLMClientProtocol
    token: str
    account_id: str | None = None


_SUPPORTED_USAGE_PROTOCOLS = {
    LLMClientProtocol.CLAUDE_OAUTH,
    LLMClientProtocol.CODEX_OAUTH,
    LLMClientProtocol.GITHUB_COPILOT_OAUTH,
}


def resolve_oauth_usage_protocol(protocol: LLMClientProtocol) -> LLMClientProtocol | None:
    """Normalize protocol to supported OAuth usage protocol ids."""
    if protocol in _SUPPORTED_USAGE_PROTOCOLS:
        return protocol
    return None


def load_oauth_usage_summary(
    *,
    protocols: set[LLMClientProtocol],
    timeout_seconds: float,
) -> dict[LLMClientProtocol, OAuthUsageSnapshot]:
    """Load OAuth usage snapshots for selected protocols.

    Failures are returned per-provider via ``error`` and never raised to caller.
    """
    auths = _resolve_provider_auths(protocols)
    if not auths:
        return {}

    snapshots: dict[LLMClientProtocol, OAuthUsageSnapshot] = {}
    max_workers = min(len(auths), 3)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        tasks = {
            executor.submit(_fetch_usage_snapshot, auth=auth, timeout_seconds=timeout_seconds): auth.protocol
            for auth in auths
        }
        for future in as_completed(tasks):
            protocol = tasks[future]
            try:
                snapshots[protocol] = future.result()
            except Exception as e:  # pragma: no cover - defensive fallback
                snapshots[protocol] = OAuthUsageSnapshot(
                    protocol=protocol,
                    windows=[],
                    error=f"{e.__class__.__name__}: {e}",
                )

    return snapshots


def format_oauth_usage_summary(snapshot: OAuthUsageSnapshot, *, max_windows: int = 2) -> str | None:
    """Format short usage summary, e.g. ``5h 62% left · Week 41% left``."""
    if snapshot.error or not snapshot.windows:
        return None

    shown = snapshot.windows[: max(1, max_windows)]
    parts = [f"{window.label} {_remaining_percent(window.used_percent):.0f}% left" for window in shown]
    summary = " · ".join(parts)

    if snapshot.plan:
        return f"{snapshot.plan} · {summary}"
    return summary


def _resolve_provider_auths(protocols: set[LLMClientProtocol]) -> list[_OAuthProviderAuth]:
    auths: list[_OAuthProviderAuth] = []

    if LLMClientProtocol.CLAUDE_OAUTH in protocols:
        try:
            token_manager = ClaudeTokenManager()
            token = ClaudeOAuth(token_manager).ensure_valid_token()
            auths.append(_OAuthProviderAuth(protocol=LLMClientProtocol.CLAUDE_OAUTH, token=token))
        except Exception:
            pass

    if LLMClientProtocol.CODEX_OAUTH in protocols:
        try:
            token_manager = CodexTokenManager()
            token = CodexOAuth(token_manager).ensure_valid_token()
            state = token_manager.get_state()
            auths.append(
                _OAuthProviderAuth(
                    protocol=LLMClientProtocol.CODEX_OAUTH,
                    token=token,
                    account_id=state.account_id if state else None,
                )
            )
        except Exception:
            pass

    if LLMClientProtocol.GITHUB_COPILOT_OAUTH in protocols:
        try:
            token_manager = CopilotTokenManager()
            state = token_manager.get_state()
            if state and state.refresh_token:
                auths.append(
                    _OAuthProviderAuth(
                        protocol=LLMClientProtocol.GITHUB_COPILOT_OAUTH,
                        token=state.refresh_token,
                    )
                )
        except Exception:
            pass

    return auths


def _fetch_usage_snapshot(*, auth: _OAuthProviderAuth, timeout_seconds: float) -> OAuthUsageSnapshot:
    match auth.protocol:
        case LLMClientProtocol.CLAUDE_OAUTH:
            return _fetch_claude_usage(token=auth.token, timeout_seconds=timeout_seconds)
        case LLMClientProtocol.CODEX_OAUTH:
            return _fetch_codex_usage(
                token=auth.token,
                account_id=auth.account_id,
                timeout_seconds=timeout_seconds,
            )
        case LLMClientProtocol.GITHUB_COPILOT_OAUTH:
            return _fetch_github_copilot_usage(token=auth.token, timeout_seconds=timeout_seconds)
        case _:
            return OAuthUsageSnapshot(protocol=auth.protocol, windows=[], error="Unsupported provider")


def _fetch_claude_usage(*, token: str, timeout_seconds: float) -> OAuthUsageSnapshot:
    with httpx.Client(timeout=timeout_seconds) as client:
        res = client.get(
            "https://api.anthropic.com/api/oauth/usage",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
                "anthropic-version": "2023-06-01",
                "anthropic-beta": ANTHROPIC_BETA_OAUTH,
                "User-Agent": "klaude-code",
            },
        )

        if res.status_code != 200:
            message = _extract_error_message(res)
            if res.status_code == 403 and message and "scope requirement user:profile" in message:
                web_fallback = _fetch_claude_web_usage(client=client)
                if web_fallback:
                    return web_fallback
            return OAuthUsageSnapshot(
                protocol=LLMClientProtocol.CLAUDE_OAUTH,
                windows=[],
                error=_build_http_error(status_code=res.status_code, message=message),
            )

        data = _as_dict(res.json())
        windows = _build_claude_windows(data)
        return OAuthUsageSnapshot(protocol=LLMClientProtocol.CLAUDE_OAUTH, windows=windows)


def _fetch_codex_usage(*, token: str, account_id: str | None, timeout_seconds: float) -> OAuthUsageSnapshot:
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "User-Agent": CODEX_USER_AGENT,
        "originator": "pi",
    }
    if account_id:
        headers["chatgpt-account-id"] = account_id

    with httpx.Client(timeout=timeout_seconds) as client:
        res = client.get("https://chatgpt.com/backend-api/wham/usage", headers=headers)
        if res.status_code != 200:
            return OAuthUsageSnapshot(
                protocol=LLMClientProtocol.CODEX_OAUTH,
                windows=[],
                error=_build_http_error(status_code=res.status_code, token_expired_statuses=(401, 403)),
            )

        data = _as_dict(res.json())
        windows: list[UsageWindowSnapshot] = []

        rate_limit = _as_dict(data.get("rate_limit")) if data else None
        primary = _as_dict(rate_limit.get("primary_window")) if rate_limit else None
        secondary = _as_dict(rate_limit.get("secondary_window")) if rate_limit else None

        if primary:
            window_seconds = _as_float(primary.get("limit_window_seconds")) or 10800.0
            hours = max(1, round(window_seconds / 3600.0))
            windows.append(
                UsageWindowSnapshot(
                    label=_hours_to_label(hours),
                    used_percent=_clamp_percent(_as_float(primary.get("used_percent")) or 0.0),
                    reset_at_epoch_ms=_parse_epoch_seconds_to_ms(primary.get("reset_at")),
                )
            )

        if secondary:
            window_seconds = _as_float(secondary.get("limit_window_seconds")) or 86400.0
            hours = max(1, round(window_seconds / 3600.0))
            label = _hours_to_label(hours)
            windows.append(
                UsageWindowSnapshot(
                    label=label,
                    used_percent=_clamp_percent(_as_float(secondary.get("used_percent")) or 0.0),
                    reset_at_epoch_ms=_parse_epoch_seconds_to_ms(secondary.get("reset_at")),
                )
            )

        plan = _as_str(data.get("plan_type")) if data else None
        credits = _as_dict(data.get("credits")) if data else None
        balance = _as_float(credits.get("balance")) if credits else None
        if balance is not None:
            balance_text = f"${balance:.2f}"
            plan = f"{plan} ({balance_text})" if plan else balance_text

        return OAuthUsageSnapshot(
            protocol=LLMClientProtocol.CODEX_OAUTH,
            windows=windows,
            plan=plan,
        )


def _fetch_github_copilot_usage(*, token: str, timeout_seconds: float) -> OAuthUsageSnapshot:
    with httpx.Client(timeout=timeout_seconds) as client:
        res = client.get(
            "https://api.github.com/copilot_internal/user",
            headers={
                "Authorization": f"token {token}",
                "X-Github-Api-Version": "2025-04-01",
                **COPILOT_STATIC_HEADERS,
            },
        )

        if res.status_code != 200:
            return OAuthUsageSnapshot(
                protocol=LLMClientProtocol.GITHUB_COPILOT_OAUTH,
                windows=[],
                error=_build_http_error(status_code=res.status_code),
            )

        data = _as_dict(res.json())
        windows: list[UsageWindowSnapshot] = []

        quota = _as_dict(data.get("quota_snapshots")) if data else None
        premium = _as_dict(quota.get("premium_interactions")) if quota else None
        chat = _as_dict(quota.get("chat")) if quota else None

        if premium:
            remaining = _as_float(premium.get("percent_remaining"))
            if remaining is not None:
                windows.append(
                    UsageWindowSnapshot(
                        label="Premium",
                        used_percent=_clamp_percent(100.0 - remaining),
                    )
                )

        if chat:
            remaining = _as_float(chat.get("percent_remaining"))
            if remaining is not None:
                windows.append(
                    UsageWindowSnapshot(
                        label="Chat",
                        used_percent=_clamp_percent(100.0 - remaining),
                    )
                )

        return OAuthUsageSnapshot(
            protocol=LLMClientProtocol.GITHUB_COPILOT_OAUTH,
            windows=windows,
            plan=_as_str(data.get("copilot_plan")) if data else None,
        )


def _build_claude_windows(data: dict[str, object] | None) -> list[UsageWindowSnapshot]:
    if not data:
        return []

    windows: list[UsageWindowSnapshot] = []

    five_hour = _as_dict(data.get("five_hour"))
    seven_day = _as_dict(data.get("seven_day"))
    seven_day_sonnet = _as_dict(data.get("seven_day_sonnet"))
    seven_day_opus = _as_dict(data.get("seven_day_opus"))

    if five_hour:
        utilization = _as_float(five_hour.get("utilization"))
        if utilization is not None:
            windows.append(
                UsageWindowSnapshot(
                    label="5h",
                    used_percent=_clamp_percent(utilization),
                    reset_at_epoch_ms=_parse_iso_datetime_to_ms(_as_str(five_hour.get("resets_at"))),
                )
            )

    if seven_day:
        utilization = _as_float(seven_day.get("utilization"))
        if utilization is not None:
            windows.append(
                UsageWindowSnapshot(
                    label="Week",
                    used_percent=_clamp_percent(utilization),
                    reset_at_epoch_ms=_parse_iso_datetime_to_ms(_as_str(seven_day.get("resets_at"))),
                )
            )

    model_window = seven_day_sonnet or seven_day_opus
    if model_window:
        utilization = _as_float(model_window.get("utilization"))
        if utilization is not None:
            windows.append(
                UsageWindowSnapshot(
                    label="Sonnet" if seven_day_sonnet else "Opus",
                    used_percent=_clamp_percent(utilization),
                )
            )

    return windows


def _fetch_claude_web_usage(*, client: httpx.Client) -> OAuthUsageSnapshot | None:
    session_key = _resolve_claude_web_session_key()
    if not session_key:
        return None

    headers = {
        "Cookie": f"sessionKey={session_key}",
        "Accept": "application/json",
    }

    org_res = client.get("https://claude.ai/api/organizations", headers=headers)
    if org_res.status_code != 200:
        return None

    orgs: object = org_res.json()
    org_id = None
    if isinstance(orgs, list):
        org_list = cast(list[object], orgs)
        first_obj: object | None = org_list[0] if org_list else None
        if first_obj is None:
            return None
        first = _as_dict(first_obj)
        if first:
            org_id = _as_str(first.get("uuid"))
    if not org_id:
        return None

    usage_res = client.get(f"https://claude.ai/api/organizations/{org_id}/usage", headers=headers)
    if usage_res.status_code != 200:
        return None

    windows = _build_claude_windows(_as_dict(usage_res.json()))
    if not windows:
        return None
    return OAuthUsageSnapshot(protocol=LLMClientProtocol.CLAUDE_OAUTH, windows=windows)


def _resolve_claude_web_session_key() -> str | None:
    direct = (os.environ.get("CLAUDE_AI_SESSION_KEY") or os.environ.get("CLAUDE_WEB_SESSION_KEY") or "").strip()
    if direct.startswith("sk-ant-"):
        return direct

    cookie_header = (os.environ.get("CLAUDE_WEB_COOKIE") or "").strip()
    if not cookie_header:
        return None

    stripped = re.sub(r"^cookie:\\s*", "", cookie_header, flags=re.IGNORECASE)
    match = re.search(r"(?:^|;\\s*)sessionKey=([^;\\s]+)", stripped, flags=re.IGNORECASE)
    value = (match.group(1) if match else "").strip()
    if value.startswith("sk-ant-"):
        return value
    return None


def _build_http_error(
    *,
    status_code: int,
    token_expired_statuses: tuple[int, ...] = (401, 403),
    message: str | None = None,
) -> str:
    if status_code in token_expired_statuses:
        return "Token expired"
    if message:
        return f"HTTP {status_code}: {message}"
    return f"HTTP {status_code}"


def _extract_error_message(response: httpx.Response) -> str | None:
    try:
        body_obj: object = response.json()
    except ValueError:
        return None

    body = _as_dict(body_obj)
    if body is not None:
        error = _as_dict(body.get("error"))
        message = _as_str(error.get("message")) if error else None
        if message:
            return message
        return _as_str(body.get("message"))
    return None


def _clamp_percent(value: float) -> float:
    if value < 0:
        return 0.0
    if value > 100:
        return 100.0
    return value


def _remaining_percent(used_percent: float) -> float:
    return _clamp_percent(100.0 - used_percent)


def _as_dict(value: object) -> dict[str, object] | None:
    if isinstance(value, dict):
        raw_dict = cast(dict[object, object], value)
        return {str(k): v for k, v in raw_dict.items()}
    return None


def _as_str(value: object) -> str | None:
    if isinstance(value, str):
        text = value.strip()
        return text or None
    return None


def _as_float(value: object) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _parse_epoch_seconds_to_ms(value: object) -> int | None:
    seconds = _as_float(value)
    if seconds is None:
        return None
    return int(seconds * 1000)


def _hours_to_label(hours: int) -> str:
    if hours >= 168:
        weeks = round(hours / 168)
        return f"{weeks}w" if weeks > 1 else "Week"
    if hours >= 24:
        days = round(hours / 24)
        return f"{days}d" if days > 1 else "Day"
    return f"{hours}h"


def _parse_iso_datetime_to_ms(value: str | None) -> int | None:
    if not value:
        return None
    try:
        parsed = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return int(parsed.timestamp() * 1000)
