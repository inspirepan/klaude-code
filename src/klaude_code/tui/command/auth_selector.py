"""Provider picker shared by CLI auth and TUI /login command."""

from __future__ import annotations

import os

from klaude_code.auth.env import get_auth_env
from klaude_code.config.builtin_config import SUPPORTED_API_KEYS
from klaude_code.tui.terminal.selector import DEFAULT_PICKER_STYLE, SelectItem, select_one


def _is_oauth_logged_in(provider_name: str) -> bool:
    try:
        match provider_name:
            case "claude":
                from klaude_code.auth.claude.token_manager import ClaudeTokenManager

                state = ClaudeTokenManager().get_state()
            case "codex":
                from klaude_code.auth.codex.token_manager import CodexTokenManager

                state = CodexTokenManager().get_state()
            case "copilot":
                from klaude_code.auth.copilot.token_manager import CopilotTokenManager

                state = CopilotTokenManager().get_state()
            case _:
                return False
        return state is not None and not state.is_expired()
    except Exception:
        return False


def _is_api_key_configured(env_var: str) -> bool:
    try:
        value = os.environ.get(env_var) or get_auth_env(env_var)
        return bool(value and value.strip())
    except Exception:
        return False


def _oauth_title(label: str, provider_name: str) -> list[tuple[str, str]]:
    title: list[tuple[str, str]] = [
        ("", f"{label} "),
        ("ansibrightblack", "[OAuth]"),
    ]
    if _is_oauth_logged_in(provider_name):
        title.append(("ansigreen", " ✓ logged in"))
    title.append(("", "\n"))
    return title


def _api_key_title(label: str, env_var: str) -> list[tuple[str, str]]:
    title: list[tuple[str, str]] = [
        ("", f"{label} "),
        ("ansibrightblack", "[API key]"),
    ]
    if _is_api_key_configured(env_var):
        title.append(("ansigreen", " ✓ configured"))
    title.append(("", "\n"))
    return title


def _is_google_vertex_configured() -> bool:
    try:
        vars = (
            "GOOGLE_APPLICATION_CREDENTIALS",
            "GOOGLE_CLOUD_PROJECT",
            "GOOGLE_CLOUD_LOCATION",
        )
        return all(bool((os.environ.get(v) or get_auth_env(v) or "").strip()) for v in vars)
    except Exception:
        return False


def _google_vertex_title() -> list[tuple[str, str]]:
    title: list[tuple[str, str]] = [
        ("", "Google Vertex "),
        ("ansibrightblack", "[Cloud credentials]"),
    ]
    if _is_google_vertex_configured():
        title.append(("ansigreen", " ✓ configured"))
    title.append(("", "\n"))
    return title


def select_provider(*, include_api_keys: bool = True, prompt: str = "Select provider to login:") -> str | None:
    """Display provider selection menu and return selected provider."""
    items: list[SelectItem[str]] = [
        SelectItem(
            title=_oauth_title("Claude Max/Pro Subscription (not recommended, use at your own risk)", "claude"),
            value="claude",
            search_text="claude",
        ),
        SelectItem(
            title=_oauth_title("ChatGPT Codex Subscription", "codex"),
            value="codex",
            search_text="codex",
        ),
        SelectItem(
            title=_oauth_title("GitHub Copilot Subscription", "copilot"),
            value="copilot",
            search_text="copilot",
        ),
    ]

    if include_api_keys:
        items.append(
            SelectItem(
                title=_google_vertex_title(),
                value="google-vertex",
                search_text="google-vertex vertex google cloud",
            )
        )
        for key_info in SUPPORTED_API_KEYS:
            items.append(
                SelectItem(
                    title=_api_key_title(key_info.name, key_info.env_var),
                    value=key_info.env_var,
                    search_text=key_info.env_var,
                )
            )

    return select_one(
        message=prompt,
        items=items,
        pointer="→",
        style=DEFAULT_PICKER_STYLE,
        use_search_filter=False,
    )
