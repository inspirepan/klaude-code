import asyncio
from typing import Literal, cast

from prompt_toolkit.styles import Style

from klaude_code.command.command_abc import Agent, CommandABC, CommandResult
from klaude_code.protocol import commands, events, llm_param, model
from klaude_code.ui.terminal.selector import SelectItem, select_one

ReasoningEffort = Literal["high", "medium", "low", "minimal", "none", "xhigh"]

# Thinking level options for different protocols
RESPONSES_LEVELS = ["low", "medium", "high"]
RESPONSES_GPT51_LEVELS = ["none", "low", "medium", "high"]
RESPONSES_GPT52_LEVELS = ["none", "low", "medium", "high", "xhigh"]
RESPONSES_CODEX_MAX_LEVELS = ["medium", "high", "xhigh"]
RESPONSES_GEMINI_FLASH_LEVELS = ["minimal", "low", "medium", "high"]

ANTHROPIC_LEVELS: list[tuple[str, int | None]] = [
    ("off", 0),
    ("low (2048 tokens)", 2048),
    ("medium (8192 tokens)", 8192),
    ("high (31999 tokens)", 31999),
]


def _is_openrouter_model_with_reasoning_effort(model_name: str | None) -> bool:
    """Check if the model is GPT series, Grok or Gemini 3."""
    if not model_name:
        return False
    model_lower = model_name.lower()
    return model_lower.startswith(("openai/gpt-", "x-ai/grok-", "google/gemini-3"))


def _is_gpt51_model(model_name: str | None) -> bool:
    """Check if the model is GPT-5.1."""
    if not model_name:
        return False
    return model_name.lower() in ["gpt-5.1", "openai/gpt-5.1", "gpt-5.1-codex-2025-11-13"]


def _is_gpt52_model(model_name: str | None) -> bool:
    """Check if the model is GPT-5.2."""
    if not model_name:
        return False
    return model_name.lower() in ["gpt-5.2", "openai/gpt-5.2"]


def _is_codex_max_model(model_name: str | None) -> bool:
    """Check if the model is GPT-5.1-codex-max."""
    if not model_name:
        return False
    return "codex-max" in model_name.lower()


def _is_gemini_flash_model(model_name: str | None) -> bool:
    """Check if the model is Gemini 3 Flash."""
    if not model_name:
        return False
    return "gemini-3-flash" in model_name.lower()


def should_auto_trigger_thinking(model_name: str | None) -> bool:
    """Check if model should auto-trigger thinking selection on switch."""
    if not model_name:
        return False
    model_lower = model_name.lower()
    return "gpt-5" in model_lower or "gemini-3" in model_lower or "opus" in model_lower


def _get_levels_for_responses(model_name: str | None) -> list[str]:
    """Get thinking levels for responses protocol."""
    if _is_codex_max_model(model_name):
        return RESPONSES_CODEX_MAX_LEVELS
    if _is_gpt52_model(model_name):
        return RESPONSES_GPT52_LEVELS
    if _is_gpt51_model(model_name):
        return RESPONSES_GPT51_LEVELS
    if _is_gemini_flash_model(model_name):
        return RESPONSES_GEMINI_FLASH_LEVELS
    return RESPONSES_LEVELS


def format_current_thinking(config: llm_param.LLMConfigParameter) -> str:
    """Format the current thinking configuration for display."""
    thinking = config.thinking
    if not thinking:
        return "not configured"

    protocol = config.protocol

    if protocol in (llm_param.LLMClientProtocol.RESPONSES, llm_param.LLMClientProtocol.CODEX):
        if thinking.reasoning_effort:
            return f"reasoning_effort={thinking.reasoning_effort}"
        return "not set"

    if protocol == llm_param.LLMClientProtocol.ANTHROPIC:
        if thinking.type == "disabled":
            return "off"
        if thinking.type == "enabled":
            return f"enabled (budget_tokens={thinking.budget_tokens})"
        return "not set"

    if protocol == llm_param.LLMClientProtocol.OPENROUTER:
        if _is_openrouter_model_with_reasoning_effort(config.model):
            if thinking.reasoning_effort:
                return f"reasoning_effort={thinking.reasoning_effort}"
        else:
            if thinking.type == "disabled":
                return "off"
            if thinking.type == "enabled":
                return f"enabled (budget_tokens={thinking.budget_tokens})"
        return "not set"

    if protocol == llm_param.LLMClientProtocol.OPENAI:
        if thinking.type == "disabled":
            return "off"
        if thinking.type == "enabled":
            return f"enabled (budget_tokens={thinking.budget_tokens})"
        return "not set"

    return "unknown protocol"


SELECT_STYLE = Style(
    [
        ("instruction", "ansibrightblack"),
        ("pointer", "ansigreen"),
        ("highlighted", "ansigreen"),
        ("text", "ansibrightblack"),
        ("question", ""),
    ]
)


def _select_responses_thinking_sync(model_name: str | None) -> llm_param.Thinking | None:
    """Select thinking level for responses/codex protocol (sync version)."""
    levels = _get_levels_for_responses(model_name)
    items: list[SelectItem[str]] = [
        SelectItem(title=[("class:text", level + "\n")], value=level, search_text=level) for level in levels
    ]

    try:
        result = select_one(
            message="Select reasoning effort:",
            items=items,
            pointer="→",
            style=SELECT_STYLE,
            use_search_filter=False,
        )

        if result is None:
            return None
        return llm_param.Thinking(reasoning_effort=cast(ReasoningEffort, result))
    except KeyboardInterrupt:
        return None


def _select_anthropic_thinking_sync() -> llm_param.Thinking | None:
    """Select thinking level for anthropic/openai_compatible protocol (sync version)."""
    items: list[SelectItem[int]] = [
        SelectItem(title=[("class:text", label + "\n")], value=tokens or 0, search_text=label)
        for label, tokens in ANTHROPIC_LEVELS
    ]

    try:
        result = select_one(
            message="Select thinking level:",
            items=items,
            pointer="→",
            style=SELECT_STYLE,
            use_search_filter=False,
        )
        if result is None:
            return None
        if result == 0:
            return llm_param.Thinking(type="disabled", budget_tokens=0)
        return llm_param.Thinking(type="enabled", budget_tokens=result)
    except KeyboardInterrupt:
        return None


async def select_thinking_for_protocol(config: llm_param.LLMConfigParameter) -> llm_param.Thinking | None:
    """Select thinking configuration based on the LLM protocol.

    Returns the selected Thinking config, or None if user cancelled.
    """
    protocol = config.protocol
    model_name = config.model

    if protocol in (llm_param.LLMClientProtocol.RESPONSES, llm_param.LLMClientProtocol.CODEX):
        return await asyncio.to_thread(_select_responses_thinking_sync, model_name)

    if protocol == llm_param.LLMClientProtocol.ANTHROPIC:
        return await asyncio.to_thread(_select_anthropic_thinking_sync)

    if protocol == llm_param.LLMClientProtocol.OPENROUTER:
        if _is_openrouter_model_with_reasoning_effort(model_name):
            return await asyncio.to_thread(_select_responses_thinking_sync, model_name)
        return await asyncio.to_thread(_select_anthropic_thinking_sync)

    if protocol == llm_param.LLMClientProtocol.OPENAI:
        return await asyncio.to_thread(_select_anthropic_thinking_sync)

    return None


class ThinkingCommand(CommandABC):
    """Configure model thinking/reasoning level."""

    @property
    def name(self) -> commands.CommandName:
        return commands.CommandName.THINKING

    @property
    def summary(self) -> str:
        return "Configure model thinking/reasoning level"

    @property
    def is_interactive(self) -> bool:
        return True

    async def run(self, agent: Agent, user_input: model.UserInputPayload) -> CommandResult:
        del user_input  # unused
        if not agent.profile:
            return self._no_change_result(agent, "No profile configured")

        config = agent.profile.llm_client.get_llm_config()
        current = format_current_thinking(config)

        new_thinking = await select_thinking_for_protocol(config)
        if new_thinking is None:
            return self._no_change_result(agent, "(no change)")

        # Apply the new thinking configuration
        config.thinking = new_thinking
        agent.session.model_thinking = new_thinking
        new_status = format_current_thinking(config)

        return CommandResult(
            events=[
                events.DeveloperMessageEvent(
                    session_id=agent.session.id,
                    item=model.DeveloperMessageItem(
                        content=f"Thinking changed: {current} -> {new_status}",
                        command_output=model.CommandOutput(command_name=self.name),
                    ),
                ),
                events.WelcomeEvent(
                    work_dir=str(agent.session.work_dir),
                    llm_config=config,
                ),
            ]
        )

    def _no_change_result(self, agent: "Agent", message: str) -> CommandResult:
        return CommandResult(
            events=[
                events.DeveloperMessageEvent(
                    session_id=agent.session.id,
                    item=model.DeveloperMessageItem(
                        content=message,
                        command_output=model.CommandOutput(command_name=self.name),
                    ),
                )
            ]
        )
