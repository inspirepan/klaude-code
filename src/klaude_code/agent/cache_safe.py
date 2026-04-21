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
from klaude_code.protocol import message


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
