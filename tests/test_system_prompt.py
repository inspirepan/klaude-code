from __future__ import annotations

from pathlib import Path

from klaude_code.agent.system_prompt import (
    SYSTEM_PROMPT_DYNAMIC_BOUNDARY,
    _build_env_info,  # pyright: ignore[reportPrivateUsage]
    build_dynamic_tool_strategy_prompt,
    load_main_base_prompt,
    load_system_prompt,
    split_system_prompt_for_cache,
    strip_system_prompt_boundary,
)
from klaude_code.protocol import llm_param, tools


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

    default_prompt = load_main_base_prompt("claude-opus-4.7")
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
    prompt = load_system_prompt("claude-opus-4.7", available_tools=[], work_dir=tmp_path)

    assert "## Response Channels" not in prompt


def test_load_system_prompt_includes_conventions_for_main_agent(tmp_path: Path) -> None:
    prompt = load_system_prompt("claude-opus-4.7", available_tools=[], work_dir=tmp_path)

    assert "# Following Conventions" in prompt
    assert "NEVER assume a given library is available" in prompt


def test_load_system_prompt_inserts_dynamic_boundary_before_auto_memory(tmp_path: Path) -> None:
    prompt = load_system_prompt("claude-opus-4.7", available_tools=[], work_dir=tmp_path)
    static_prompt, dynamic_prompt = split_system_prompt_for_cache(prompt)

    assert SYSTEM_PROMPT_DYNAMIC_BOUNDARY in prompt
    assert static_prompt is not None and "# auto memory" not in static_prompt
    assert dynamic_prompt is not None and dynamic_prompt.startswith("# auto memory")


def test_strip_system_prompt_boundary_restores_plain_prompt_text() -> None:
    prompt = "static\n\n__SYSTEM_PROMPT_DYNAMIC_BOUNDARY__\n\ndynamic"

    assert strip_system_prompt_boundary(prompt) == "static\n\ndynamic"


def test_load_system_prompt_includes_extended_thinking_for_adaptive_models(tmp_path: Path) -> None:
    opus47_prompt = load_system_prompt("claude-opus-4-7", available_tools=[], work_dir=tmp_path)
    assert "# Extended Thinking" in opus47_prompt

    opus46_prompt = load_system_prompt("claude-opus-4-6", available_tools=[], work_dir=tmp_path)
    assert "# Extended Thinking" in opus46_prompt

    sonnet_prompt = load_system_prompt("claude-sonnet-4-6", available_tools=[], work_dir=tmp_path)
    assert "# Extended Thinking" in sonnet_prompt


def test_load_system_prompt_excludes_extended_thinking_for_non_adaptive_models(tmp_path: Path) -> None:
    prompt = load_system_prompt("gpt-5.4", available_tools=[], work_dir=tmp_path)
    assert "# Extended Thinking" not in prompt


def test_load_system_prompt_does_not_embed_available_skills_listing(tmp_path: Path) -> None:
    prompt = load_system_prompt("claude-opus-4.7", available_tools=[], work_dir=tmp_path)

    assert "<available_skills>" not in prompt
    assert "Skills are optional task-specific instructions stored as `SKILL.md` files." not in prompt


def test_dynamic_tool_strategy_prompt_prefers_finder_for_multi_step_search() -> None:
    prompt = build_dynamic_tool_strategy_prompt(
        [llm_param.ToolSchema(name=tools.AGENT, type="function", description="agent", parameters={})]
    )

    assert "cross-directory tracing" in prompt
    assert "concept-based searches" in prompt
    assert "chain multiple search steps" in prompt
    assert '`type="finder"`' in prompt
