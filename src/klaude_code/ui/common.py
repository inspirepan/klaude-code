from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from klaude_code.protocol.llm_param import LLMConfigModelParameter, OpenRouterProviderRouting


def format_number(tokens: int) -> str:
    if tokens < 1000:
        return f"{tokens}"
    elif tokens < 1000000:
        # 12.3k
        k = tokens / 1000
        if k == int(k):
            return f"{int(k)}k"
        else:
            return f"{k:.1f}k"
    else:
        # 2M345k
        m = tokens // 1000000
        remaining = (tokens % 1000000) // 1000
        if remaining == 0:
            return f"{m}M"
        else:
            return f"{m}M{remaining}k"


def format_model_params(model_params: "LLMConfigModelParameter") -> list[str]:
    """Format model parameters in a concise style.

    Returns a list of formatted parameter strings like:
    - "reasoning medium"
    - "thinking budget 10000"
    - "verbosity 2"
    - "image generation"
    - "provider-routing: {…}"
    """
    parts: list[str] = []

    if model_params.thinking:
        if model_params.thinking.reasoning_effort:
            parts.append(f"reasoning {model_params.thinking.reasoning_effort}")
        if model_params.thinking.reasoning_summary:
            parts.append(f"summary {model_params.thinking.reasoning_summary}")
        if model_params.thinking.budget_tokens:
            parts.append(f"thinking budget {model_params.thinking.budget_tokens}")

    if model_params.verbosity:
        parts.append(f"verbosity {model_params.verbosity}")

    if model_params.provider_routing:
        parts.append(f"provider routing {_format_provider_routing(model_params.provider_routing)}")

    if model_params.modalities and any(m.casefold() == "image" for m in model_params.modalities):
        parts.append("image generation")

    if model_params.image_config:
        if model_params.image_config.aspect_ratio:
            parts.append(f"image aspect {model_params.image_config.aspect_ratio}")
        if model_params.image_config.image_size:
            parts.append(f"image size {model_params.image_config.image_size}")

    return parts


def _format_provider_routing(pr: "OpenRouterProviderRouting") -> str:
    """Format provider routing settings concisely."""
    items: list[str] = []
    if pr.sort:
        items.append(pr.sort)
    if pr.only:
        items.append(">".join(pr.only))
    if pr.order:
        items.append(">".join(pr.order))
    if pr.ignore:
        items.append(f"ignore {'>'.join(pr.ignore)}")
    return " · ".join(items) if items else ""
