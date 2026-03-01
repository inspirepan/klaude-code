from __future__ import annotations

import json
from pathlib import Path

from klaude_code.auth.copilot.token_manager import CopilotTokenManager


def _copilot_state_payload() -> dict[str, object]:
    return {
        "access_token": "copilot-access-token",
        "refresh_token": "github-access-token",
        "expires_at": 4102444800,
        "enterprise_domain": None,
        "copilot_base_url": "https://api.individual.githubcopilot.com",
    }


def test_load_migrates_legacy_copilot_storage_key(tmp_path: Path) -> None:
    auth_file = tmp_path / "klaude-auth.json"
    auth_file.write_text(json.dumps({"copilot": _copilot_state_payload()}))

    token_manager = CopilotTokenManager(auth_file=auth_file)
    state = token_manager.get_state()

    assert state is not None
    assert state.access_token == "copilot-access-token"

    saved = json.loads(auth_file.read_text())
    assert "github-copilot" in saved
    assert "copilot" not in saved


def test_delete_cleans_legacy_and_new_copilot_storage_keys(tmp_path: Path) -> None:
    auth_file = tmp_path / "klaude-auth.json"
    auth_file.write_text(
        json.dumps(
            {
                "copilot": _copilot_state_payload(),
                "github-copilot": _copilot_state_payload(),
                "env": {"OPENAI_API_KEY": "test"},
            }
        )
    )

    token_manager = CopilotTokenManager(auth_file=auth_file)
    token_manager.delete()

    saved = json.loads(auth_file.read_text())
    assert "copilot" not in saved
    assert "github-copilot" not in saved
    assert saved["env"]["OPENAI_API_KEY"] == "test"