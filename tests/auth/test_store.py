from pathlib import Path

import pytest

from klaude_code.auth import base, env, removed_provider
from klaude_code.auth.chatgpt.token_manager import ChatGPTAuthState, ChatGPTTokenManager
from klaude_code.auth.store import load_store, save_store


def test_auth_writers_share_path_and_preserve_other_sections(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "nested" / "auth.json"
    monkeypatch.setattr(base, "KLAUDE_AUTH_FILE", path)
    save_store(path, {"copilot": {"access_token": "legacy"}})
    env.set_auth_env("OPENAI_API_KEY", "test-key")
    manager = ChatGPTTokenManager()
    state = ChatGPTAuthState(access_token="access", refresh_token="refresh", expires_at=4102444800, client_id="test")
    manager.save(state)

    assert removed_provider.delete_removed_github_copilot_auth_state()
    assert load_store(path) == {"env": {"OPENAI_API_KEY": "test-key"}, "chatgpt": state.model_dump(mode="json")}
    assert env.get_auth_env("OPENAI_API_KEY") == "test-key"
    assert ChatGPTTokenManager().load() == state

    env.delete_auth_env("OPENAI_API_KEY")
    assert load_store(path) == {"chatgpt": state.model_dump(mode="json")}
    manager.delete()
    assert not path.exists()

    save_store(path, {})
    assert path.read_text() == "{}"
