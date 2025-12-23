"""Factory helpers for building :class:`LLMClients` from config."""

from __future__ import annotations

from klaude_code.config import Config
from klaude_code.core.manager.llm_clients import LLMClients
from klaude_code.llm.client import LLMClientABC
from klaude_code.llm.registry import create_llm_client
from klaude_code.protocol.sub_agent import iter_sub_agent_profiles
from klaude_code.protocol.tools import SubAgentType
from klaude_code.trace import DebugType, log_debug


def build_llm_clients(
    config: Config,
    *,
    model_override: str | None = None,
) -> LLMClients:
    """Create an ``LLMClients`` bundle driven by application config."""

    # Resolve main agent LLM config
    model_name = model_override or config.main_model
    if model_name is None:
        raise ValueError("No model specified. Use --model or --select-model to specify a model.")
    llm_config = config.get_model_config(model_name)

    log_debug(
        "Main LLM config",
        llm_config.model_dump_json(exclude_none=True),
        style="yellow",
        debug_type=DebugType.LLM_CONFIG,
    )

    main_client = create_llm_client(llm_config)
    sub_clients: dict[SubAgentType, LLMClientABC] = {}

    for profile in iter_sub_agent_profiles():
        model_name = config.sub_agent_models.get(profile.name)
        if not model_name:
            continue

        if not profile.enabled_for_model(main_client.model_name):
            continue

        sub_llm_config = config.get_model_config(model_name)
        sub_clients[profile.name] = create_llm_client(sub_llm_config)

    return LLMClients(main=main_client, sub_clients=sub_clients)
