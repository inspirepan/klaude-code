"""Model identification utilities.

Centralised helpers that identify model families by name pattern.
This module lives in ``protocol`` so that both ``llm`` and ``config``
layers can import it without violating the layered-architecture contract.
"""


# -- Anthropic ----------------------------------------------------------------


def is_opus_46_model(model_name: str | None) -> bool:
    """Check if the model is Claude Opus 4.6."""
    if not model_name:
        return False
    model_lower = model_name.lower()
    return "opus-4-6" in model_lower or "opus-4.6" in model_lower


def is_sonnet_46_model(model_name: str | None) -> bool:
    """Check if the model is Claude Sonnet 4.6."""
    if not model_name:
        return False
    model_lower = model_name.lower()
    return "sonnet-4-6" in model_lower or "sonnet-4.6" in model_lower


def supports_adaptive_thinking(model_name: str | None) -> bool:
    """Check if the model supports adaptive thinking (Opus 4.6 or Sonnet 4.6)."""
    return is_opus_46_model(model_name) or is_sonnet_46_model(model_name)


def is_claude_model(model_name: str | None) -> bool:
    """Return True if the model name represents an Anthropic Claude model (OpenRouter prefix)."""
    return model_name is not None and model_name.startswith("anthropic/claude")


def is_claude_model_any(model_name: str | None) -> bool:
    """Return True if the model name contains 'claude' (any provider/format)."""
    return model_name is not None and "claude" in model_name.lower()


def model_supports_unsigned_thinking(model_name: str | None) -> bool:
    """Check if the model supports thinking blocks without signature (e.g., kimi, deepseek)."""
    if not model_name:
        return False
    model_lower = model_name.lower()
    return "kimi" in model_lower or "deepseek" in model_lower


# -- OpenAI / Responses -------------------------------------------------------


def is_gpt51_model(model_name: str | None) -> bool:
    """Check if the model is GPT-5.1."""
    if not model_name:
        return False
    return model_name.lower() in ["gpt-5.1", "openai/gpt-5.1", "gpt-5.1-codex-2025-11-13"]


def is_gpt52_model(model_name: str | None) -> bool:
    """Check if the model is GPT-5.2 or GPT-5.3 (same thinking levels)."""
    if not model_name:
        return False
    return model_name.lower() in ["gpt-5.2", "openai/gpt-5.2", "gpt-5.3", "openai/gpt-5.3"]


def is_gpt5_model(model_name: str | None) -> bool:
    """Check if the model is any GPT-5 variant."""
    if not model_name:
        return False
    return "gpt-5" in model_name.lower()


# -- Google --------------------------------------------------------------------


def is_gemini_model(model_name: str | None) -> bool:
    """Return True if the model name represents a Google Gemini model (OpenRouter prefix)."""
    return model_name is not None and model_name.startswith("google/gemini")


def is_gemini_model_any(model_name: str | None) -> bool:
    """Return True if the model name contains 'gemini' (any provider/format)."""
    return model_name is not None and "gemini" in model_name.lower()


def is_gemini3_model(model_name: str | None) -> bool:
    """Check if the model is any Gemini 3 variant."""
    if not model_name:
        return False
    return "gemini-3" in model_name.lower()


def is_gemini_flash_model(model_name: str | None) -> bool:
    """Check if the model is Gemini 3 Flash."""
    if not model_name:
        return False
    return "gemini-3-flash" in model_name.lower()


def supports_google_thinking(model_name: str | None) -> bool:
    """Check if the Google model supports thinking (Gemini 3 or Gemini 2.5 Pro)."""
    if not model_name:
        return False
    return "gemini-3" in model_name or "gemini-2.5-pro" in model_name


# -- Zhipu (GLM) ---------------------------------------------------------------


def is_glm_model(model_name: str | None) -> bool:
    """Return True if the model is GLM-5 or GLM-4.7 (supports preserved thinking)."""
    if not model_name:
        return False
    model_lower = model_name.lower()
    return "glm-5" in model_lower or "glm-4.7" in model_lower


# -- xAI -----------------------------------------------------------------------


def is_xai_model(model_name: str | None) -> bool:
    """Return True if the model name represents an xAI model (OpenRouter prefix)."""
    return model_name is not None and model_name.startswith("x-ai/")


def is_grok_model(model_name: str | None) -> bool:
    """Return True if the model name contains 'grok' (any provider/format)."""
    return model_name is not None and "grok" in model_name.lower()


# -- OpenRouter composite checks -----------------------------------------------


def is_openrouter_model_with_reasoning_effort(model_name: str | None) -> bool:
    """Check if the model is GPT series, Grok or Gemini 3 (OpenRouter models with reasoning_effort support)."""
    if not model_name:
        return False
    model_lower = model_name.lower()
    return model_lower.startswith(("openai/gpt-", "x-ai/grok-", "google/gemini-3"))
