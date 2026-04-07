from __future__ import annotations

from pathlib import Path

from klaude_code.prompts.system_prompt import (
    _build_env_info,  # pyright: ignore[reportPrivateUsage]
    load_main_base_prompt,
    load_system_prompt,
)


def test_build_env_info_handles_missing_work_dir(tmp_path: Path) -> None:
    missing_dir = tmp_path / "workspace"

    env_info = _build_env_info("gpt-5.3-codex", missing_dir)

    assert f"Working directory: {missing_dir} (not found)" in env_info
    assert "Current directory is not a git repo" in env_info


def test_load_main_base_prompt_routes_gpt5_to_gpt_prompt() -> None:
    gpt_prompt = load_main_base_prompt("gpt-5.4")
    assert "Pragmatism and Scope" in gpt_prompt
    assert "Autonomy and Persistence" in gpt_prompt
    assert "## Response Channels" in gpt_prompt

    default_prompt = load_main_base_prompt("claude-opus-4.6")
    assert "Pragmatism and Scope" not in default_prompt
    assert "## Response Channels" not in default_prompt


def test_gpt5_prompt_includes_response_channels_from_base(tmp_path: Path) -> None:
    prompt = load_system_prompt("gpt-5.4", available_tools=[], work_dir=tmp_path)

    assert "## Response Channels" in prompt
    assert "`commentary` channel" in prompt
    assert "`final` channel" in prompt
    # Response channels come from the base prompt, not duplicated by phase injection
    assert prompt.count("## Response Channels") == 1


def test_load_system_prompt_excludes_channels_for_non_gpt5_models(tmp_path: Path) -> None:
    prompt = load_system_prompt("claude-opus-4.6", available_tools=[], work_dir=tmp_path)

    assert "## Response Channels" not in prompt


def test_load_system_prompt_includes_conventions_for_main_agent(tmp_path: Path) -> None:
    prompt = load_system_prompt("claude-opus-4.6", available_tools=[], work_dir=tmp_path)

    assert "# Following Conventions" in prompt
    assert "NEVER assume a given library is available" in prompt


def test_load_system_prompt_includes_extended_thinking_for_adaptive_models(tmp_path: Path) -> None:
    opus_prompt = load_system_prompt("claude-opus-4-6", available_tools=[], work_dir=tmp_path)
    assert "# Extended Thinking" in opus_prompt

    sonnet_prompt = load_system_prompt("claude-sonnet-4-6", available_tools=[], work_dir=tmp_path)
    assert "# Extended Thinking" in sonnet_prompt


def test_load_system_prompt_excludes_extended_thinking_for_non_adaptive_models(tmp_path: Path) -> None:
    prompt = load_system_prompt("gpt-5.4", available_tools=[], work_dir=tmp_path)
    assert "# Extended Thinking" not in prompt


def test_load_system_prompt_does_not_embed_available_skills_listing(tmp_path: Path) -> None:
    prompt = load_system_prompt("claude-opus-4.6", available_tools=[], work_dir=tmp_path)

    assert "<available_skills>" not in prompt
    assert "Skills are optional task-specific instructions stored as `SKILL.md` files." not in prompt
