from __future__ import annotations

from klaude_code.agent.compaction.overflow import is_context_overflow
from klaude_code.agent.runtime.llm import FallbackLLMClient, ModelFallback
from klaude_code.llm import LLMClientABC
from klaude_code.protocol import events, message
from klaude_code.protocol.tools import SubAgentType


def fallback_reason(error_message: str) -> str:
    first_line = error_message.strip().splitlines()[0] if error_message.strip() else "LLM request failed"
    return first_line[:500]


def is_fallbackable_llm_error(error_message: str) -> bool:
    text = error_message.casefold()
    if is_context_overflow(error_message):
        return False
    fallbackable_markers = (
        "insufficient_quota",
        "exceeded your current quota",
        "quota exceeded",
        "quota_exceeded",
        "billing",
        "credit balance",
        "credits exhausted",
        "insufficient credits",
        "payment required",
        "model_not_found",
        "model_not_available",
        "does not have access to model",
        "not authorized to access",
        "permission_denied",
        "permission denied",
        "usage_limit_reached",
    )
    return any(marker in text for marker in fallbackable_markers)


def fallback_llm_client(client: LLMClientABC, error_message: str) -> ModelFallback | None:
    if not isinstance(client, FallbackLLMClient):
        return None
    if not is_fallbackable_llm_error(error_message):
        return None
    return client.fallback_to_next()


def build_fallback_model_config_warn(
    *,
    session_id: str,
    fallback: ModelFallback,
    error_message: str,
    sub_agent_type: SubAgentType | None = None,
) -> tuple[message.FallbackModelConfigWarnEntry, events.FallbackModelConfigWarnEvent]:
    reason = fallback_reason(error_message)
    entry = message.FallbackModelConfigWarnEntry(
        sub_agent_type=sub_agent_type,
        from_model=fallback.from_candidate.model_name,
        from_provider=fallback.from_candidate.provider,
        to_model=fallback.to_candidate.model_name,
        to_provider=fallback.to_candidate.provider,
        reason=reason,
    )
    event = events.FallbackModelConfigWarnEvent(
        session_id=session_id,
        sub_agent_type=entry.sub_agent_type,
        from_model=entry.from_model,
        from_provider=entry.from_provider,
        to_model=entry.to_model,
        to_provider=entry.to_provider,
        reason=entry.reason,
    )
    return entry, event
