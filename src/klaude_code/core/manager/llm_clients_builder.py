"""Factory helpers for building :class:`LLMClients` from config."""

from __future__ import annotations

from klaude_code.config import Config
from klaude_code.config.sub_agent_model_helper import SubAgentModelHelper
from klaude_code.core.manager.llm_clients import LLMClients
from klaude_code.llm.client import LLMClientABC
from klaude_code.llm.registry import create_llm_client
from klaude_code.log import DebugType, log_debug
from klaude_code.protocol.sub_agent import get_sub_agent_profile
from klaude_code.protocol.tools import SubAgentType


def build_llm_clients(
    config: Config,
    *,
    model_override: str | None = None,
    skip_sub_agents: bool = False,
) -> LLMClients:
    """Create an ``LLMClients`` bundle driven by application config.

    Args:
        config: Application configuration.
        model_override: Override for the main model name.
        skip_sub_agents: If True, skip initializing sub-agent clients.
    """

    # Resolve main agent LLM config
    model_name = model_override or config.main_model
    if model_name is None:
        raise ValueError("No model specified. Set main_model in the config or pass --model.")
    llm_config = config.get_model_config(model_name)

    log_debug(
        "Main LLM config",
        llm_config.model_dump_json(exclude_none=True),
        style="yellow",
        debug_type=DebugType.LLM_CONFIG,
    )

    main_client = create_llm_client(llm_config)

    # Build compact client if configured
    compact_client: LLMClientABC | None = None
    if config.compact_model:
        compact_llm_config = config.get_model_config(config.compact_model)
        log_debug(
            "Compact LLM config",
            compact_llm_config.model_dump_json(exclude_none=True),
            style="yellow",
            debug_type=DebugType.LLM_CONFIG,
        )
        compact_client = create_llm_client(compact_llm_config)

    if skip_sub_agents:
        return LLMClients(main=main_client, main_model_alias=model_name, compact=compact_client)

    helper = SubAgentModelHelper(config)
    sub_agent_configs = helper.build_sub_agent_client_configs()

    # User-configured sub_agent_models take precedence; builtin role configs are soft-fallback.
    user_sub_agent_models = config.get_user_sub_agent_models()

    sub_clients: dict[SubAgentType, LLMClientABC] = {}
    for sub_agent_type, sub_model_name in sub_agent_configs.items():
        try:
            sub_llm_config = config.get_model_config(sub_model_name)
            sub_clients[sub_agent_type] = create_llm_client(sub_llm_config)
        except ValueError:
            profile = get_sub_agent_profile(sub_agent_type)
            role_key = profile.invoker_type
            if role_key is not None and role_key in user_sub_agent_models:
                raise
            log_debug(
                f"Sub-agent '{sub_agent_type}' builtin model '{sub_model_name}' not available, falling back to main model",
                style="yellow",
                debug_type=DebugType.LLM_CONFIG,
            )

    return LLMClients(main=main_client, main_model_alias=model_name, sub_clients=sub_clients, compact=compact_client)
