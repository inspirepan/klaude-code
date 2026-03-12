from __future__ import annotations

from pathlib import Path

from klaude_code.core.prompts.system_prompt import (
    _build_env_info,  # pyright: ignore[reportPrivateUsage]
    load_system_prompt,
)


def test_build_env_info_handles_missing_work_dir(tmp_path: Path) -> None:
    missing_dir = tmp_path / "workspace"

    env_info = _build_env_info("gpt-5.3-codex", missing_dir)

    assert f"Working directory: {missing_dir} (not found)" in env_info
    assert "Current directory is not a git repo" in env_info


def test_load_system_prompt_includes_phase_guidance_for_gpt54(tmp_path: Path) -> None:
    prompt = load_system_prompt("gpt-5.4", available_tools=[], work_dir=tmp_path)

    assert "# Working with the user" in prompt
    assert "Share intermediary updates in `commentary` channel." in prompt
    assert "send a message to the `final` channel" in prompt


def test_load_system_prompt_excludes_phase_guidance_for_non_phase_models(tmp_path: Path) -> None:
    prompt = load_system_prompt("gpt-4.1", available_tools=[], work_dir=tmp_path)

    assert "# Working with the user" not in prompt
