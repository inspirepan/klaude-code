"""Cache-safe LLM request construction for forked queries.

A forked LLM query (compact, handoff, sub-agent fork_context, etc.) wants to
piggy-back on the parent session's server-side prompt cache. The Anthropic API
cache key is composed of:

- system prompt
- tools (schema)
- model id
- thinking config
- messages prefix (byte-identical)

:class:`CacheSafeParams` packages these five so any caller producing an LLM
request whose wire prefix must match the parent's most recent request can pass
it around explicitly instead of relying on implicit convention.

Traps to avoid when populating / consuming these params:

- Do not pass ``tools=[]`` to deny tool use in the fork; that changes the cache
  key. Keep the parent's tools intact and deny at the ``can_use_tool`` callback
  layer instead.
- Setting ``max_output_tokens`` on the fork request may clamp the thinking
  ``budget_tokens`` in the LLM layer, changing the cache key. Only set it when
  cache sharing is not a goal.
- ``prefix_messages`` must be produced by the same transform the parent used on
  its last request. Prefer :meth:`Session.get_llm_history` rather than hand
  assembling from ``conversation_history``.
"""

from __future__ import annotations

from dataclasses import dataclass

from klaude_code.agent.agent_profile import AgentProfile
from klaude_code.llm import LLMClientABC
from klaude_code.protocol import events, message
from klaude_code.protocol.models import Usage


@dataclass(frozen=True)
class CacheSafeParams:
    """Parameters that must match the parent request to share its prompt cache.

    Cache key = (system, tools, model, thinking, messages prefix).

    The first four come from :attr:`profile`; the fifth is :attr:`prefix_messages`.
    """

    profile: AgentProfile
    """Provides system prompt, tools, model id, and thinking config.
    Must be the same :class:`AgentProfile` the parent's last request used.
    """

    prefix_messages: list[message.HistoryEvent]
    """The exact message prefix the parent's last LLM request sent.
    Typically ``session.get_llm_history()`` from the parent session.
    """


def build_cache_safe_messages(
    cache_safe: CacheSafeParams,
    extra: list[message.HistoryEvent],
) -> list[message.HistoryEvent]:
    """Append fork-specific messages after the parent's wire prefix.

    The returned list has :attr:`CacheSafeParams.prefix_messages` as its prefix
    byte-for-byte, so the server-side prompt cache built on the parent's last
    request is reusable. Only ``extra`` adds new bytes that will be cached
    fresh (or not, if the caller sets a ``skip_cache_write`` flag downstream).
    """
    return [*cache_safe.prefix_messages, *extra]


def is_cache_sharable(main_profile: AgentProfile, secondary_client: LLMClientABC) -> bool:
    """Return True when ``secondary_client``'s request will hit ``main_profile``'s prompt cache.

    Compares the cache-key components that can diverge between a main-loop request
    and a forked request: model_id, provider_name, and thinking config. The
    remaining components (system prompt, tools, message prefix) are enforced by
    the fork call site reusing ``main_profile`` and the session's LLM history.
    """
    main_cfg = main_profile.llm_client.get_llm_config()
    other_cfg = secondary_client.get_llm_config()
    if main_cfg.model_id != other_cfg.model_id:
        return False
    if main_cfg.provider_name != other_cfg.provider_name:
        return False
    return main_cfg.thinking == other_cfg.thinking


def build_fork_cache_event(
    *, session_id: str, fork_label: str, usage: Usage | None, fallback_used: bool
) -> events.ForkCacheHitRateEvent:
    """Construct a ForkCacheHitRateEvent for a completed fork request.

    ``usage`` is the final assistant message's Usage from the fork; pass ``None``
    for fallback paths that don't produce comparable usage, which yields an event
    with zeroed token counts and ``cache_hit_rate=0.0``.
    """
    if usage is None:
        return events.ForkCacheHitRateEvent(
            session_id=session_id,
            fork_label=fork_label,
            cache_read_tokens=0,
            cache_creation_tokens=0,
            input_tokens=0,
            cache_hit_rate=0.0,
            fallback_used=fallback_used,
        )
    # ``Usage.input_tokens`` is provider-dependent: Anthropic/OpenAI paths store it
    # as the full prompt total (cached + write + non-cached), while others use only
    # the non-cached portion. ``max(input_tokens, cached + write)`` normalizes to
    # the true total prompt size across providers (same trick as CacheTracker).
    total = max(usage.input_tokens, usage.cached_tokens + usage.cache_write_tokens)
    hit_rate = usage.cached_tokens / total if total > 0 else 0.0
    return events.ForkCacheHitRateEvent(
        session_id=session_id,
        fork_label=fork_label,
        cache_read_tokens=usage.cached_tokens,
        cache_creation_tokens=usage.cache_write_tokens,
        input_tokens=max(0, total - usage.cached_tokens - usage.cache_write_tokens),
        cache_hit_rate=hit_rate,
        fallback_used=fallback_used,
    )
