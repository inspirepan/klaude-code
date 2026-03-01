from klaude_code.config.thinking import format_current_thinking, get_thinking_picker_data
from klaude_code.protocol import llm_param


def test_github_copilot_claude_picker_uses_anthropic_style() -> None:
    config = llm_param.LLMConfigParameter(
        protocol=llm_param.LLMClientProtocol.GITHUB_COPILOT_OAUTH,
        model_id="claude-sonnet-4-6",
    )

    picker = get_thinking_picker_data(config)

    assert picker is not None
    assert picker.message == "Select thinking level:"
    assert picker.options[-1].value == "adaptive:adaptive"


def test_github_copilot_gpt_picker_uses_responses_style() -> None:
    config = llm_param.LLMConfigParameter(
        protocol=llm_param.LLMClientProtocol.GITHUB_COPILOT_OAUTH,
        model_id="gpt-5.3-codex",
    )

    picker = get_thinking_picker_data(config)

    assert picker is not None
    assert picker.message == "Select reasoning effort:"
    assert picker.options[0].value.startswith("effort:")


def test_format_current_thinking_for_github_copilot_claude_budget() -> None:
    config = llm_param.LLMConfigParameter(
        protocol=llm_param.LLMClientProtocol.GITHUB_COPILOT_OAUTH,
        model_id="claude-sonnet-4-6",
        thinking=llm_param.Thinking(type="enabled", budget_tokens=2048),
    )

    assert format_current_thinking(config) == "enabled (budget_tokens=2048)"
