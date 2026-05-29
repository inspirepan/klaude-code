"""Shared stop-reason mapping for LLM providers.

Providers report finish/stop reasons under different vocabularies. This module
holds the small set of reasons shared across the Anthropic/Bedrock/Google
clients and a helper that layers per-provider overrides on top, so each client
keeps byte-identical behavior while sharing the common entries.
"""

from klaude_code.protocol.models import StopReason

# Reasons shared across the Anthropic, Bedrock and Google clients.
# Per-provider maps extend this via the ``overrides`` argument of
# ``map_stop_reason`` to add their provider-specific reasons.
_COMMON_STOP_REASON_MAP: dict[str, StopReason] = {
    "end_turn": "stop",
    "max_tokens": "length",
    "tool_use": "tool_use",
}


def map_stop_reason(raw: str, overrides: dict[str, StopReason] | None = None) -> StopReason | None:
    """Map a provider stop reason, applying per-provider overrides over the common map."""
    mapping = _COMMON_STOP_REASON_MAP if not overrides else {**_COMMON_STOP_REASON_MAP, **overrides}
    return mapping.get(raw)
