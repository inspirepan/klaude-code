from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from klaude_code.protocol.llm_param import LLMConfigModelParameter, OpenRouterProviderRouting

def format_number(tokens: int) -> str:
    if tokens < 1000:
        return f"{tokens}"
    if tokens < 1000000:
        k = tokens / 1000
        if k == int(k):
            return f"{int(k)}k"
        return f"{k:.1f}k"

    m = tokens // 1000000
    remaining = (tokens % 1000000) // 1000
    if remaining == 0:
        return f"{m}M"
    return f"{m}M{remaining}k"

def format_model_params(model_params: "LLMConfigModelParameter") -> list[str]:
    parts: list[str] = []

    if model_params.thinking:
        if model_params.thinking.type == "adaptive":
            parts.append("adaptive thinking")
        elif model_params.thinking.reasoning_effort:
            parts.append(f"reasoning {model_params.thinking.reasoning_effort}")
        if model_params.thinking.reasoning_summary:
            parts.append(f"summary {model_params.thinking.reasoning_summary}")
        if model_params.thinking.budget_tokens:
            parts.append(f"thinking budget {model_params.thinking.budget_tokens}")

    if model_params.effort:
        parts.append(f"effort {model_params.effort}")

    if model_params.verbosity:
        parts.append(f"verbosity {model_params.verbosity}")

    if model_params.fast_mode:
        parts.append("fast mode")

    if model_params.provider_routing:
        parts.append(f"provider routing {_format_provider_routing(model_params.provider_routing)}")

    return parts

def _format_provider_routing(pr: "OpenRouterProviderRouting") -> str:
    items: list[str] = []
    if pr.sort:
        items.append(pr.sort)
    if pr.only:
        items.append(" > ".join(pr.only))
    if pr.order:
        items.append(" > ".join(pr.order))
    if pr.ignore:
        items.append(f"ignore {' > '.join(pr.ignore)}")
    return " · ".join(items) if items else ""
