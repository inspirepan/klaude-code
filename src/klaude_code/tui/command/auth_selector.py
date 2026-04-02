"""Provider picker shared by CLI auth and TUI /login command."""

from __future__ import annotations

import os

from klaude_code.auth.env import get_auth_env
from klaude_code.config.builtin_config import SUPPORTED_API_KEYS
from klaude_code.tui.terminal.selector import DEFAULT_PICKER_STYLE, SelectItem, select_one


def _get_oauth_auth_state(provider_name: str) -> tuple[bool, bool]:
    """Return (has_auth_state, is_expired)."""
    try:
        match provider_name:
            case "codex":
                from klaude_code.auth.codex.token_manager import CodexTokenManager

                state = CodexTokenManager().get_state()
            case "github-copilot" | "copilot":
                from klaude_code.auth.copilot.token_manager import CopilotTokenManager

                state = CopilotTokenManager().get_state()
            case _:
                return False, False
        if state is None:
            return False, False
        return True, state.is_expired()
    except Exception:
        return False, False


def _api_key_source(env_var: str) -> str | None:
    """Return the source of the API key: 'env' for OS environment, 'configured' for auth store, or None."""
    try:
        env_value = os.environ.get(env_var)
        if env_value and env_value.strip():
            return "env"
        auth_value = get_auth_env(env_var)
        if auth_value and auth_value.strip():
            return "configured"
        return None
    except Exception:
        return None


def _oauth_title(label: str, provider_name: str) -> list[tuple[str, str]]:
    title: list[tuple[str, str]] = [
        ("", f"{label} "),
        ("ansibrightblack", "[OAuth]"),
    ]
    has_state, is_expired = _get_oauth_auth_state(provider_name)
    if has_state and not is_expired:
        title.append(("ansigreen", " ✓ logged in"))
    elif has_state and is_expired:
        title.append(("ansiyellow", " · token expired (refresh on use)"))
    title.append(("", "\n"))
    return title


def _api_key_title(label: str, env_var: str) -> list[tuple[str, str]]:
    title: list[tuple[str, str]] = [
        ("", f"{label} "),
        ("ansibrightblack", f"[{env_var}]"),
    ]
    source = _api_key_source(env_var)
    if source == "env":
        title.append(("ansigreen", " ✓ env"))
    elif source == "configured":
        title.append(("ansigreen", " ✓ configured"))
    title.append(("", "\n"))
    return title


def _google_vertex_source() -> str | None:
    """Return the source of Google Vertex credentials: 'env', 'configured', or None."""
    try:
        required_vars = (
            "GOOGLE_APPLICATION_CREDENTIALS",
            "GOOGLE_CLOUD_PROJECT",
            "GOOGLE_CLOUD_LOCATION",
        )
        all_from_env = True
        all_present = True
        for v in required_vars:
            env_value = os.environ.get(v)
            if env_value and env_value.strip():
                continue
            all_from_env = False
            auth_value = get_auth_env(v)
            if not (auth_value and auth_value.strip()):
                all_present = False
                break
        if not all_present:
            return None
        return "env" if all_from_env else "configured"
    except Exception:
        return None


def _google_vertex_title() -> list[tuple[str, str]]:
    title: list[tuple[str, str]] = [
        ("", "Google Vertex "),
        ("ansibrightblack", "[Cloud credentials]"),
    ]
    source = _google_vertex_source()
    if source == "env":
        title.append(("ansigreen", " ✓ env"))
    elif source == "configured":
        title.append(("ansigreen", " ✓ configured"))
    title.append(("", "\n"))
    return title


def select_provider(*, include_api_keys: bool = True, prompt: str = "Select provider to login:") -> str | None:
    """Display provider selection menu and return selected provider."""
    items: list[SelectItem[str]] = [
        SelectItem(
            title=_oauth_title("ChatGPT Codex Subscription", "codex"),
            value="codex",
            search_text="codex",
        ),
        SelectItem(
            title=_oauth_title("GitHub Copilot Subscription", "github-copilot"),
            value="github-copilot",
            search_text="github-copilot github copilot",
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
