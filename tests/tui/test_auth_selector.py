from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from klaude_code.auth import base as auth_base
from klaude_code.tui.command import auth_selector
from klaude_code.tui.terminal.selector import SelectItem


def test_logout_selector_shows_removed_github_copilot_cleanup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    auth_file = tmp_path / "klaude-auth.json"
    auth_file.write_text(json.dumps({"github-copilot": {"access_token": "old"}}))
    selected_items: list[SelectItem[str]] = []

    def _select_one(*, items: list[SelectItem[str]], **_: Any) -> str | None:
        selected_items.extend(items)
        return items[0].value if items else None

    monkeypatch.setattr(auth_base, "KLAUDE_AUTH_FILE", auth_file)
    monkeypatch.setattr(auth_selector, "_get_oauth_auth_state", lambda _provider: (False, False))
    monkeypatch.setattr(auth_selector, "select_one", _select_one)

    selected = auth_selector.select_provider(include_api_keys=False, configured_only=True)

    assert selected == "github-copilot"
    assert [item.value for item in selected_items] == ["github-copilot"]
    title_text = "".join(text for _style, text in selected_items[0].title)
    assert "cleanup only" in title_text


def test_selector_includes_xai_and_filters_unconfigured(monkeypatch: pytest.MonkeyPatch) -> None:
    selected_items: list[SelectItem[str]] = []

    def _select_one(*, items: list[SelectItem[str]], **_: Any) -> str | None:
        selected_items.extend(items)
        return None

    monkeypatch.setattr(auth_selector, "select_one", _select_one)
    monkeypatch.setattr(
        auth_selector,
        "_get_oauth_auth_state",
        lambda provider: (provider == "xai", False),
    )

    auth_selector.select_provider(include_api_keys=False, configured_only=True)

    assert [item.value for item in selected_items] == ["xai"]
