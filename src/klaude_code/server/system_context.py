"""On-demand system prompt + tool catalogue for the viewer's SYSTEM inspector.

Neither the system prompt nor the tool schemas belong in a status frame that
refreshes on every model change -- together they are tens of kilobytes -- so the
viewer asks for them once, when a reader opens the SYSTEM row.

Two sources, and the answer says which one it is:

- ``live``: the loaded agent's own profile, i.e. the exact ``system`` / ``tools``
  the next step would send.
- ``rebuilt``: for a cold session, the same builders run again off the session
  meta (model name, work_dir, agent type). Prompt assembly reads prompt files
  and probes the work_dir; it never constructs an LLM client, touches the
  network, or writes anything. It reflects TODAY's prompt files and tool set,
  not what the session actually sent, so readers must label it as rebuilt.

Model config is reported through an explicit allowlist of display fields rather
than a model dump: no credential can reach the response by being added upstream.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Final

from klaude_code.agent.agent_profile import AgentProfile, load_agent_tools
from klaude_code.agent.system_prompt import load_system_prompt
from klaude_code.protocol import llm_param
from klaude_code.tool.core.registry import get_tool_schemas

CACHE_TTL_SECONDS: Final = 30.0

# session_id -> (expires_at_monotonic, payload)
_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}

# Vanilla sessions strip the profile down to these; mirrors
# ``agent/agent_profile.py:VanillaModelProfileProvider``.
_VANILLA_SYSTEM_PROMPT: Final = "You're an agent running in user's terminal"
_VANILLA_TOOLS: Final = ["Bash", "Edit", "Write", "Read"]


def clear_cache() -> None:
    _CACHE.clear()


def _tool_payload(schemas: list[llm_param.ToolSchema]) -> list[dict[str, Any]]:
    return [{"name": tool.name, "description": tool.description, "parameters": tool.parameters} for tool in schemas]


def _live_model_payload(config: llm_param.LLMConfigParameter, model_config_name: str | None) -> dict[str, Any]:
    """Allowlisted display fields. Never widen this to a model dump."""
    thinking = config.thinking
    return {
        "provider": config.provider_name or None,
        "protocol": config.protocol.value,
        "model": config.model_id,
        "model_config_name": model_config_name,
        "effort": config.effective_effort,
        "max_tokens": config.max_tokens,
        "context_limit": config.context_limit,
        "temperature": config.temperature,
        "verbosity": config.verbosity,
        "thinking": thinking.model_dump(mode="json", exclude_none=True) if thinking is not None else None,
        "fast_mode": config.fast_mode,
        "cache_retention": config.cache_retention,
        "supports_vision": config.supports_vision,
    }


def _cold_model_payload(meta: dict[str, Any]) -> dict[str, Any]:
    """What meta.json remembers about the model. No config lookup, no secrets."""
    thinking = meta.get("model_thinking")
    effort = meta.get("model_effort")
    if not isinstance(effort, str):
        effort = None
    return {
        "provider": None,
        "protocol": None,
        "model": meta.get("model_name") if isinstance(meta.get("model_name"), str) else None,
        "model_config_name": meta.get("model_config_name") if isinstance(meta.get("model_config_name"), str) else None,
        "effort": effort,
        "max_tokens": None,
        "context_limit": None,
        "temperature": None,
        "verbosity": None,
        "thinking": thinking if isinstance(thinking, dict) else None,
        "fast_mode": None,
        "cache_retention": None,
        "supports_vision": None,
    }


def live_payload(profile: AgentProfile, *, model_config_name: str | None) -> dict[str, Any]:
    return {
        "available": True,
        "source": "live",
        "system_prompt": profile.system_prompt,
        "tools": _tool_payload(profile.tools),
        "model": _live_model_payload(profile.llm_client.get_llm_config(), model_config_name),
        "reason": None,
    }


def rebuilt_payload(meta: dict[str, Any], work_dir: Path) -> dict[str, Any]:
    """Re-run the prompt/tool builders off session meta. Read-only."""
    model_name = meta.get("model_name")
    if not isinstance(model_name, str) or not model_name:
        config_name = meta.get("model_config_name")
        model_name = config_name if isinstance(config_name, str) else ""
    if bool(meta.get("vanilla", False)):
        return {
            "available": True,
            "source": "rebuilt",
            "system_prompt": _VANILLA_SYSTEM_PROMPT,
            "tools": _tool_payload(get_tool_schemas(_VANILLA_TOOLS)),
            "model": _cold_model_payload(meta),
            "reason": None,
        }
    agent_type = meta.get("agent_type")
    sub_agent_type = agent_type if isinstance(agent_type, str) and agent_type else None
    try:
        # supports_vision is a per-model config flag the meta does not keep; the
        # only effect of the default is whether LookAt is appended.
        tools = load_agent_tools(model_name, sub_agent_type, supports_vision=True)
        system_prompt = load_system_prompt(model_name, sub_agent_type, available_tools=tools, work_dir=work_dir)
    except (KeyError, OSError, ValueError) as exc:
        return unavailable(f"rebuild failed: {exc.__class__.__name__}: {exc}")
    return {
        "available": True,
        "source": "rebuilt",
        "system_prompt": system_prompt,
        "tools": _tool_payload(tools),
        "model": _cold_model_payload(meta),
        "reason": None,
    }


def unavailable(reason: str) -> dict[str, Any]:
    return {
        "available": False,
        "source": None,
        "system_prompt": None,
        "tools": None,
        "model": None,
        "reason": reason,
    }


def cached(session_id: str) -> dict[str, Any] | None:
    hit = _CACHE.get(session_id)
    if hit is None:
        return None
    expires_at, payload = hit
    if expires_at <= time.monotonic():
        _CACHE.pop(session_id, None)
        return None
    return payload


def store(session_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    _CACHE[session_id] = (time.monotonic() + CACHE_TTL_SECONDS, payload)
    return payload


__all__ = [
    "CACHE_TTL_SECONDS",
    "cached",
    "clear_cache",
    "live_payload",
    "rebuilt_payload",
    "store",
    "unavailable",
]
