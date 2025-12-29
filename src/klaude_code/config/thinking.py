"""Thinking level configuration data and helpers.

This module contains thinking level definitions and helper functions
that are shared between command layer and UI layer.
"""

from typing import Literal

from klaude_code.protocol import llm_param

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


def is_openrouter_model_with_reasoning_effort(model_name: str | None) -> bool:
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


def get_levels_for_responses(model_name: str | None) -> list[str]:
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
        if is_openrouter_model_with_reasoning_effort(config.model):
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
