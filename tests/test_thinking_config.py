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


def test_opus_47_picker_only_shows_adaptive_options() -> None:
    config = llm_param.LLMConfigParameter(
        protocol=llm_param.LLMClientProtocol.ANTHROPIC,
        model_id="claude-opus-4-7",
    )

    picker = get_thinking_picker_data(config)

    assert picker is not None
    values = [opt.value for opt in picker.options]
    assert values == ["adaptive:disabled", "adaptive:adaptive"]


def test_opus_47_openrouter_picker_only_shows_adaptive_options() -> None:
    config = llm_param.LLMConfigParameter(
        protocol=llm_param.LLMClientProtocol.OPENROUTER,
        model_id="anthropic/claude-opus-4.7",
    )

    picker = get_thinking_picker_data(config)

    assert picker is not None
    values = [opt.value for opt in picker.options]
    assert values == ["adaptive:disabled", "adaptive:adaptive"]


def test_opus_47_bedrock_picker_only_shows_adaptive_options() -> None:
    config = llm_param.LLMConfigParameter(
        protocol=llm_param.LLMClientProtocol.BEDROCK,
        model_id="us.anthropic.claude-opus-4-7",
        thinking=llm_param.Thinking(type="disabled"),
    )

    picker = get_thinking_picker_data(config)

    assert picker is not None
    values = [opt.value for opt in picker.options]
    assert values == ["adaptive:disabled", "adaptive:adaptive"]
    assert picker.current_value == "adaptive:disabled"
