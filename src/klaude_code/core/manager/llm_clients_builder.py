"""Factory helpers for building :class:`LLMClients` from config."""

from __future__ import annotations

from klaude_code.config import Config
from klaude_code.core.manager.llm_clients import LLMClients
from klaude_code.llm.client import LLMClientABC
from klaude_code.llm.registry import create_llm_client
from klaude_code.protocol.sub_agent import get_sub_agent_profile
from klaude_code.protocol.tools import SubAgentType
from klaude_code.trace import DebugType, log_debug


def build_llm_clients(
    config: Config,
    *,
    model_override: str | None = None,
    enabled_sub_agents: list[SubAgentType] | None = None,
) -> LLMClients:
    """Create an ``LLMClients`` bundle driven by application config."""

    # Resolve main agent LLM config
    if model_override:
        llm_config = config.get_model_config(model_override)
    else:
        llm_config = config.get_main_model_config()

    log_debug(
        "Main LLM config",
        llm_config.model_dump_json(exclude_none=True),
        style="yellow",
        debug_type=DebugType.LLM_CONFIG,
    )

    main_client = create_llm_client(llm_config)
    sub_clients: dict[SubAgentType, LLMClientABC] = {}

    # Initialize sub-agent clients
    for sub_agent_type in enabled_sub_agents or []:
        model_name = config.subagent_models.get(sub_agent_type)
        if not model_name:
            continue
        profile = get_sub_agent_profile(sub_agent_type)
        if not profile.enabled_for_model(main_client.model_name):
            continue
        sub_llm_config = config.get_model_config(model_name)
        sub_clients[sub_agent_type] = create_llm_client(sub_llm_config)

    return LLMClients(main=main_client, sub_clients=sub_clients)
