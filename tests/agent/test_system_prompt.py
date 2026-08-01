from __future__ import annotations

from pathlib import Path

import pytest

import klaude_code.agent.system_prompt as system_prompt_module
from klaude_code.agent.system_prompt import (
    SYSTEM_PROMPT_DYNAMIC_BOUNDARY,
    _build_env_info,  # pyright: ignore[reportPrivateUsage]
    load_system_prompt,
    split_system_prompt_for_cache,
    strip_system_prompt_boundary,
)


def test_load_main_base_prompt_routes_by_model_family(monkeypatch: pytest.MonkeyPatch) -> None:
    loaded_paths: list[str] = []

    def _load(prompt_path: str) -> str:
        loaded_paths.append(prompt_path)
        return prompt_path

    monkeypatch.setattr(system_prompt_module, "load_prompt_by_path", _load)

    assert system_prompt_module.load_main_base_prompt("gpt-5.4") == "prompts/system/base-system-prompt-gpt.md"
    assert system_prompt_module.load_main_base_prompt("claude-opus-4.7") == "prompts/system/base-system-prompt.md"
    assert loaded_paths == ["prompts/system/base-system-prompt-gpt.md", "prompts/system/base-system-prompt.md"]


def test_build_env_info_handles_missing_work_dir(tmp_path: Path) -> None:
    missing_dir = tmp_path / "workspace"

    env_info = _build_env_info("gpt-5.3-codex", missing_dir)

    assert f"Working directory: {missing_dir} (not found)" in env_info
    assert "Current directory is not a jj or git repo" in env_info


def test_build_env_info_prefers_jj_repo(tmp_path: Path) -> None:
    (tmp_path / ".jj").mkdir()
    (tmp_path / ".git").mkdir()
    work_dir = tmp_path / "src"
    work_dir.mkdir()

    env_info = _build_env_info("gpt-5.3-codex", work_dir)

    assert f"Current directory is a jj repo (root: {tmp_path})" in env_info
    assert "Current directory is a git repo" not in env_info


def test_build_env_info_falls_back_to_git_repo(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    work_dir = tmp_path / "src"
    work_dir.mkdir()

    env_info = _build_env_info("gpt-5.3-codex", work_dir)

    assert f"Current directory is a git repo (root: {tmp_path})" in env_info


def test_load_system_prompt_inserts_dynamic_boundary_before_env_info(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(system_prompt_module, "_build_env_info", lambda _model, _work_dir: "\n\nDYNAMIC_SENTINEL")

    prompt = load_system_prompt("claude-opus-4.7", available_tools=[], work_dir=tmp_path)
    static_prompt, dynamic_prompt = split_system_prompt_for_cache(prompt)

    assert SYSTEM_PROMPT_DYNAMIC_BOUNDARY in prompt
    assert static_prompt is not None
    assert "DYNAMIC_SENTINEL" not in static_prompt
    assert dynamic_prompt == "DYNAMIC_SENTINEL"


def test_strip_system_prompt_boundary_restores_plain_prompt_text() -> None:
    prompt = "static\n\n__SYSTEM_PROMPT_DYNAMIC_BOUNDARY__\n\ndynamic"

    assert strip_system_prompt_boundary(prompt) == "static\n\ndynamic"
